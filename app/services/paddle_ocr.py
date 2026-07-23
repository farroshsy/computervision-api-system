import contextlib
import os
import logging
import tempfile
import time
import random
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
import cv2
import numpy as np
# On Windows the paddle-gpu wheel ships cuDNN/CUDA DLLs under
# site-packages/nvidia/*/bin but never puts them on the DLL search path, so
# conv ops fail to load cudnn ("WinError 127"). Register them before importing
# paddle. No-op on CPU-only installs (no nvidia dir) and off Windows.
def _register_cuda_dll_dirs():
    if os.name != "nt":
        return
    import glob
    import site
    roots = list(site.getsitepackages())
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass
    seen = set()
    for sp in roots:
        for d in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
            if d not in seen and os.path.isdir(d):
                seen.add(d)
                try:
                    os.add_dll_directory(d)
                except OSError:
                    pass


# GPU (Windows paddle-gpu) opt-in only. BOTH steps below are needed only for
# the GPU wheel and are actively HARMFUL on the CPU box:
#  - registering the CUDA DLL dirs pollutes torch's own DLL resolution;
#  - importing paddle eagerly here reorders imports so paddle loads before
#    torch, after which torch's shm.dll fails to load (WinError 127).
# So do neither unless GPU is explicitly requested. On CPU (default), paddle
# is imported lazily by paddlex as before, torch loads first, both coexist.
# (The eager import dodges a circular-import crash unique to the GPU wheel.)
if os.getenv("PPOCR_USE_GPU") == "1":
    _register_cuda_dll_dirs()
    import paddle  # noqa: F401
import paddleocr as _paddleocr_pkg
from paddleocr import PaddleOCR
from typing import List, Tuple, Optional, Union

# paddleocr 3.x replaced .ocr() with .predict() and dropped the 'latin'
# model (English v5 model handles Latin-script Indonesian). One compat
# flag + one normalization point (OCRService.run_ocr) keeps the rest of
# the pipeline identical across both major versions.
try:
    PADDLEOCR_V3 = int(str(getattr(_paddleocr_pkg, "__version__", "2")).split(".")[0]) >= 3
except (ValueError, TypeError):
    PADDLEOCR_V3 = False
from app.utils.preprocess import preprocess_image_for_ocr, detect_and_correct_skew

logger = logging.getLogger(__name__)

# The Paddle CPU predictor is NOT thread-safe: two concurrent requests
# (e.g. rapid drag&drop uploads) segfault the whole process. Inference
# already saturates all cores, so serializing costs no throughput.
import threading

_INFERENCE_LOCK = threading.Lock()


def _resolve_use_gpu() -> bool:
    """Pick the device automatically: GPU when one is actually usable, CPU
    otherwise — so the SAME code runs on the GPU box and on an Intel Mac with
    nothing to configure. PPOCR_USE_GPU still forces it (1=gpu, 0=cpu) when set.

    "Usable" means the installed Paddle was built with CUDA AND a device is
    visible; the CPU-only wheel (e.g. on the Mac) reports is_compiled_with_cuda
    False and falls through to CPU. Any probe failure also means CPU."""
    forced = os.getenv('PPOCR_USE_GPU')
    if forced is not None:
        return forced.strip() == '1'
    try:
        import paddle
        return bool(paddle.device.is_compiled_with_cuda()
                    and paddle.device.cuda.device_count() > 0)
    except Exception:
        return False

# ONE thread, for the entire process lifetime, for every Paddle predict call.
#
# Each OCR attempt used to open its own `ThreadPoolExecutor(max_workers=1)`, so
# every predict ran on a BRAND-NEW thread. The Paddle CPU predictor is not just
# thread-unsafe (which _INFERENCE_LOCK already handles) — it is thread-AFFINE:
# driven from a different thread each call, the C++ side intermittently throws
# `std::exception`, the page reads as 0 lines, and the request silently falls
# back to a degraded path. That is what made the SAME image return a correct
# name on one run and digit-soup on the next.
#
# A single long-lived worker makes every predict happen on the thread that has
# been running them all along, which is the access pattern Paddle expects.
_OCR_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paddle-ocr")


@contextlib.contextmanager
def _ocr_worker():
    """The shared OCR thread, borrowed — and NOT shut down on exit.

    Shaped as a context manager so the call sites read unchanged; the point is
    precisely that leaving the block must not dispose of the thread.
    """
    yield _OCR_EXECUTOR


class OCRService:
    """Service for handling OCR operations with PaddleOCR"""
    
    def __init__(self):
        """Initialize PaddleOCR with optimized settings"""
        # Language and device can be configured via environment variables
        # PPOCR_LANG: e.g., 'multi' (default), 'en', 'ch', 'japan', etc.
        # PPOCR_USE_GPU: '1' to enable GPU when available, else CPU
        lang = os.getenv('PPOCR_LANG', 'multi')
        # Normalize unsupported 'multi' for PaddleOCR 2.7.x which expects concrete langs
        if isinstance(lang, str) and lang.lower() in {'multi', 'multi_lang', 'multi-language'}:
            logger.info("PPOCR_LANG '%s' not supported by this PaddleOCR version; coercing to 'latin'", lang)
            lang = 'latin'
        if PADDLEOCR_V3 and lang == 'latin':
            # v3 ships no 'latin' model; the v5 English model covers
            # Latin-script Indonesian (measured +16pts on the eval set)
            lang = 'en'
        use_gpu = _resolve_use_gpu()
        # Debug-save control
        self.debug_save = os.getenv('PPOCR_DEBUG_SAVE', '0') == '1'
        self.debug_dir = os.getenv('PPOCR_DEBUG_DIR', os.path.join(os.getcwd(), 'debug_preproc'))
        if self.debug_save:
            try:
                os.makedirs(self.debug_dir, exist_ok=True)
                logger.info("Debug-save enabled; intermediates will be copied to: %s", self.debug_dir)
            except Exception as _e:
                logger.warning("Failed to create debug dir %s: %s", self.debug_dir, str(_e))

        logger.info(f"Initializing PaddleOCR with lang='{lang}', use_gpu={use_gpu}")

        if PADDLEOCR_V3:
            # doc_orientation_classify auto-corrects 90/180/270-rotated
            # photos before detection (measured: rotations cost up to 14
            # fields on the eval set without it)
            #
            # This branch used to hardcode CPU and return, so PPOCR_USE_GPU=1
            # silently did nothing on the v3 pipeline: the flag existed, the
            # log line even printed use_gpu=True, and every predict still ran on
            # the CPU. Honour it — a GPU box is the whole reason to set it.
            # Requires a CUDA build of paddle (see requirements-gpu.txt); with
            # the CPU wheel installed, asking for 'gpu' raises, so fall back
            # loudly rather than pretending.
            device = 'gpu' if use_gpu else 'cpu'
            try:
                self.ocr = PaddleOCR(
                    lang=lang,
                    device=device,
                    use_textline_orientation=True,
                    use_doc_orientation_classify=True,
                    use_doc_unwarping=False,
                )
            except Exception as e:
                if device == 'gpu':
                    logger.warning(
                        "GPU requested but PaddleOCR could not start on it (%s). "
                        "Falling back to CPU — install paddlepaddle-gpu to use the GPU.",
                        str(e))
                    device = 'cpu'
                self.ocr = PaddleOCR(
                    lang=lang,
                    use_textline_orientation=True,
                    use_doc_orientation_classify=True,
                    use_doc_unwarping=False,
                )
            self.lang = lang
            self._device = device
            self._switched_to_cpu = (device == 'cpu')
            logger.info("PaddleOCR v3 pipeline initialized (lang=%s, device=%s)",
                        lang, device)
            return
        # Initialize with minimal, widely-supported arguments to ensure compatibility
        try:
            # Newer/older versions may differ on GPU flag; attempt progressively
            try:
                self.ocr = PaddleOCR(
                    use_angle_cls=True,
                    lang=lang,
                    use_gpu=use_gpu
                )
            except (TypeError, ValueError):
                # Try device keyword (some versions)
                device = 'gpu' if use_gpu else 'cpu'
                try:
                    self.ocr = PaddleOCR(
                        use_angle_cls=True,
                        lang=lang,
                        device=device
                    )
                except (TypeError, ValueError):
                    # Last resort: minimal args
                    self.ocr = PaddleOCR(
                        use_angle_cls=True,
                        lang=lang
                    )
        except Exception as ve:
            # Fallback when language models are not available (e.g., 'multi' missing)
            logger.warning(
                "PaddleOCR init failed for lang='%s' (%s). Falling back to lang='en'.",
                lang,
                str(ve),
            )
            # Retry with 'en' across possible signatures
            try:
                try:
                    self.ocr = PaddleOCR(
                        use_angle_cls=True,
                        lang='en',
                        use_gpu=use_gpu
                    )
                except (TypeError, ValueError):
                    device = 'gpu' if use_gpu else 'cpu'
                    try:
                        self.ocr = PaddleOCR(
                            use_angle_cls=True,
                            lang='en',
                            device=device
                        )
                    except (TypeError, ValueError):
                        self.ocr = PaddleOCR(
                            use_angle_cls=True,
                            lang='en'
                        )
            except Exception as e:
                logger.error("PaddleOCR fallback init failed: %s", str(e))
                raise
        # Track device/lang for dynamic re-init
        self.lang = lang
        self._device = 'gpu' if use_gpu else 'cpu'
        self._switched_to_cpu = False

    def run_ocr(self, image_path: str):
        """Run OCR and return the LEGACY v2 result shape regardless of the
        installed paddleocr major version:
            [[ [poly_points, (text, confidence)], ... ]]
        so every downstream parser keeps working unchanged.
        Serialized via _INFERENCE_LOCK — see note at the lock."""
        with _INFERENCE_LOCK:
            return self._run_ocr_unlocked(image_path)

    def _run_ocr_unlocked(self, image_path: str):
        if not PADDLEOCR_V3:
            return self.ocr.ocr(image_path)
        results = self.ocr.predict(image_path)
        lines = []
        for res in results or []:
            texts = res.get('rec_texts') if hasattr(res, 'get') else None
            if texts is None:
                continue
            scores = res.get('rec_scores') or [0.9] * len(texts)
            polys = res.get('rec_polys')
            for i, (t, s) in enumerate(zip(texts, scores)):
                try:
                    poly = [[float(x), float(y)] for x, y in polys[i]] if polys is not None else [[0, 0]] * 4
                except (TypeError, IndexError, ValueError):
                    poly = [[0, 0]] * 4
                lines.append([poly, (str(t), float(s))])
        return [lines]

    def _reinit_ocr(self, lang: str, device: str) -> None:
        """Re-initialize PaddleOCR with requested device, handling signature differences."""
        logger.warning("Reinitializing PaddleOCR with device=%s (lang=%s)", device, lang)
        use_gpu_flag = (device == 'gpu')
        try:
            try:
                self.ocr = PaddleOCR(
                    use_angle_cls=True,
                    lang=lang,
                    use_gpu=use_gpu_flag
                )
            except (TypeError, ValueError):
                try:
                    self.ocr = PaddleOCR(
                        use_angle_cls=True,
                        lang=lang,
                        device=device
                    )
                except (TypeError, ValueError):
                    self.ocr = PaddleOCR(
                        use_angle_cls=True,
                        lang=lang
                    )
            self._device = device
        except Exception as e:
            logger.error("Failed to reinit OCR with device=%s: %s", device, str(e))
            raise
        
    def preprocess_image(self, image_path: str, doc_type: Optional[str] = None) -> str:
        """Enhanced image preprocessing for better OCR results"""
        try:
            # Read image
            img = cv2.imread(image_path)
            if img is None:
                raise ValueError(f"Failed to read image: {image_path}")
                
            # Convert to grayscale
            if len(img.shape) == 3:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                gray = img
                
            # Resize if too large (for performance)
            height, width = gray.shape
            if max(height, width) > 2000:
                scale = 2000 / max(height, width)
                new_width = int(width * scale)
                new_height = int(height * scale)
                gray = cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_AREA)
                
            # Per-document preprocessing pipeline
            dt = (doc_type or "").upper()
            if dt in {"KTP", "SIM"}:
                # deskew + CLAHE + mild sharpen
                gray = detect_and_correct_skew(gray)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                gray = clahe.apply(gray)
                blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
                sharpen = cv2.addWeighted(gray, 1.5, blur, -0.5, 0)
                proc = sharpen
            elif dt in {"STNK", "KIR"}:
                # denoise + adaptive thresholding tuned + morphology to connect strokes
                den = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
                thr = cv2.adaptiveThreshold(
                    den, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5
                )
                try:
                    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
                    proc = cv2.morphologyEx(thr, cv2.MORPH_CLOSE, kernel_close, iterations=1)
                    # light dilation to reinforce faint strokes
                    kernel_dil = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                    proc = cv2.dilate(proc, kernel_dil, iterations=1)
                except Exception:
                    proc = thr
            else:
                # default adaptive thresholding
                proc = cv2.adaptiveThreshold(
                    gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
                )
            
            # Save the preprocessed image
            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"preprocessed_{os.path.basename(image_path)}")
            cv2.imwrite(output_path, proc)
            # Optionally copy to debug folder
            if getattr(self, 'debug_save', False):
                try:
                    dbg_path = os.path.join(self.debug_dir, os.path.basename(output_path))
                    cv2.imwrite(dbg_path, proc)
                except Exception as _e:
                    logger.debug("Debug-save failed for %s: %s", output_path, str(_e))
            
            return output_path
            
        except Exception as e:
            logger.error(f"Image preprocessing failed: {str(e)}")
            return image_path  # Return original if preprocessing fails
    
    def preprocess_image_alt(self, image_path: str, doc_type: Optional[str] = None) -> str:
        """Alternative preprocessing pipeline used as a fallback when no text is detected.
        - For KTP/SIM: try adaptive thresholding instead of CLAHE+sharpen.
        - For STNK/KIR: adjust adaptive threshold parameters (larger block size, lower C).
        """
        try:
            img = cv2.imread(image_path)
            if img is None:
                raise ValueError(f"Failed to read image: {image_path}")

            if len(img.shape) == 3:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                gray = img

            # Resize if too large
            h, w = gray.shape
            if max(h, w) > 2200:
                scale = 2200 / max(h, w)
                gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

            dt = (doc_type or "").upper()
            if dt in {"KTP", "SIM"}:
                # Alternative: adaptive threshold
                proc = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 3)
            elif dt in {"STNK", "KIR"}:
                # Alternative: different parameters
                den = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
                proc = cv2.adaptiveThreshold(den, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 3)
            else:
                proc = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, 2)

            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"preprocessed_alt_{os.path.basename(image_path)}")
            cv2.imwrite(output_path, proc)
            if getattr(self, 'debug_save', False):
                try:
                    dbg_path = os.path.join(self.debug_dir, os.path.basename(output_path))
                    cv2.imwrite(dbg_path, proc)
                except Exception as _e:
                    logger.debug("Debug-save failed for %s: %s", output_path, str(_e))
            return output_path
        except Exception as e:
            logger.error(f"Alt preprocessing failed: {str(e)}")
            return image_path
    
    def preprocess_image_sim_fallback2(self, image_path: str) -> str:
        """Aggressive SIM-specific fallback preprocessing.
        Steps:
        - Use HSV V channel to normalize illumination
        - Strong CLAHE for contrast
        - Optional denoise to reduce compression artifacts
        - Unsharp mask to enhance edges
        - Combined OTSU ∨ Adaptive Gaussian ∨ Sauvola local threshold (binary)
        - Morphological close followed by light open to connect characters and remove specks
        - Upscale if image is small to aid recognition (higher target)
        """
        try:
            img = cv2.imread(image_path)
            if img is None:
                raise ValueError(f"Failed to read image: {image_path}")

            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            v = hsv[:, :, 2]

            # Upscale more aggressively for small SIM cards
            h, w = v.shape
            target = 1300
            if max(h, w) < target:
                scale = target / max(h, w)
                v = cv2.resize(v, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

            # Strong CLAHE
            clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
            v_eq = clahe.apply(v)

            # Optional fast denoise for JPEG/compression artifacts
            try:
                v_dn = cv2.fastNlMeansDenoising(v_eq, None, h=7, templateWindowSize=7, searchWindowSize=21)
            except Exception:
                v_dn = v_eq

            # Unsharp mask
            blur = cv2.GaussianBlur(v_dn, (0, 0), 1.2)
            sharp = cv2.addWeighted(v_dn, 1.7, blur, -0.7, 0)

            # Combine OTSU with Adaptive Gaussian to handle uneven lighting
            try:
                _, thr_otsu = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            except Exception:
                thr_otsu = sharp
            try:
                thr_adp = cv2.adaptiveThreshold(sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                cv2.THRESH_BINARY, 21, 7)
            except Exception:
                thr_adp = thr_otsu
            # Sauvola threshold (manual implementation)
            try:
                win = 21
                k = 0.34
                R = 128.0
                sharp_f = sharp.astype(np.float32)
                m = cv2.boxFilter(sharp_f, ddepth=-1, ksize=(win, win), normalize=True)
                sq = cv2.boxFilter(sharp_f * sharp_f, ddepth=-1, ksize=(win, win), normalize=True)
                v = np.maximum(sq - m * m, 0.0)
                s = cv2.sqrt(v)
                thresh = m * (1.0 + k * ((s / R) - 1.0))
                thr_sau = np.where(sharp_f > thresh, 255, 0).astype(np.uint8)
            except Exception:
                thr_sau = thr_adp
            try:
                tmp_or = cv2.bitwise_or(thr_otsu, thr_adp)
                thr = cv2.bitwise_or(tmp_or, thr_sau)
            except Exception:
                thr = thr_otsu

            # Morphology: close then light open
            try:
                k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
                tmp = cv2.morphologyEx(thr, cv2.MORPH_CLOSE, k_close, iterations=1)
                k_open = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                proc = cv2.morphologyEx(tmp, cv2.MORPH_OPEN, k_open, iterations=1)
            except Exception:
                proc = thr

            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"preprocessed_sim2_{os.path.basename(image_path)}")
            cv2.imwrite(output_path, proc)
            if getattr(self, 'debug_save', False):
                try:
                    dbg_path = os.path.join(self.debug_dir, os.path.basename(output_path))
                    cv2.imwrite(dbg_path, proc)
                except Exception as _e:
                    logger.debug("Debug-save failed for %s: %s", output_path, str(_e))
            return output_path
        except Exception as e:
            logger.error(f"SIM fallback2 preprocessing failed: {str(e)}")
            return image_path

    def preprocess_image_sim_denoise_alt(self, image_path: str) -> str:
        """SIM alternative preprocessing emphasizing denoise before thresholding.
        Steps:
        - Bilateral filter to reduce noise while preserving edges
        - Optional fastNlMeansDenoisingColored for heavy noise
        - Adaptive Gaussian threshold
        - Light morphology open
        """
        try:
            img = cv2.imread(image_path)
            if img is None:
                return image_path
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            # Edge-preserving denoise
            den_bi = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)
            try:
                # Extra denoise on color then back to gray if beneficial
                den_col = cv2.fastNlMeansDenoisingColored(img, None, 7, 7, 7, 21)
                den_gray = cv2.cvtColor(den_col, cv2.COLOR_BGR2GRAY)
                base = cv2.addWeighted(den_bi, 0.6, den_gray, 0.4, 0)
            except Exception:
                base = den_bi
            thr = cv2.adaptiveThreshold(base, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 3)
            try:
                k_open = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                proc = cv2.morphologyEx(thr, cv2.MORPH_OPEN, k_open, iterations=1)
            except Exception:
                proc = thr
            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"preprocessed_sim_dn_{os.path.basename(image_path)}")
            cv2.imwrite(output_path, proc)
            if getattr(self, 'debug_save', False):
                try:
                    dbg_path = os.path.join(self.debug_dir, os.path.basename(output_path))
                    cv2.imwrite(dbg_path, proc)
                except Exception as _e:
                    logger.debug("Debug-save failed for %s: %s", output_path, str(_e))
            return output_path
        except Exception as e:
            logger.error(f"SIM denoise-alt preprocessing failed: {str(e)}")
            return image_path
    def _rotate_image_temp(self, image_path: str, angle_deg: float) -> str:
        """Rotate image by a small angle and save to a temp file, preserving bounds."""
        img = cv2.imread(image_path)
        if img is None:
            return image_path
        h, w = img.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
        cos = abs(M[0, 0]); sin = abs(M[0, 1])
        # compute new bounds
        nW = int((h * sin) + (w * cos))
        nH = int((h * cos) + (w * sin))
        # adjust rotation matrix to take into account translation
        M[0, 2] += (nW / 2) - center[0]
        M[1, 2] += (nH / 2) - center[1]
        rotated = cv2.warpAffine(img, M, (nW, nH), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        temp_dir = tempfile.gettempdir()
        out = os.path.join(temp_dir, f"rot_{int(angle_deg*10)}_{os.path.basename(image_path)}")
        cv2.imwrite(out, rotated)
        if getattr(self, 'debug_save', False):
            try:
                dbg_path = os.path.join(self.debug_dir, os.path.basename(out))
                cv2.imwrite(dbg_path, rotated)
            except Exception as _e:
                logger.debug("Debug-save failed for %s: %s", out, str(_e))
        return out

    def preprocess_image_ktp_fallback2(self, image_path: str) -> str:
        """More aggressive KTP-specific fallback preprocessing.
        Steps:
        - Use HSV V channel for robust illumination handling
        - Contrast boost with CLAHE (stronger clipLimit)
        - Unsharp mask
        - Global OTSU threshold
        - Light morphology open to reduce background noise
        """
        try:
            img = cv2.imread(image_path)
            if img is None:
                raise ValueError(f"Failed to read image: {image_path}")

            # Convert to HSV and take V channel
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            v = hsv[:, :, 2]

            # Resize up slightly if small to help OCR
            h, w = v.shape
            if max(h, w) < 900:
                scale = 900 / max(h, w)
                v = cv2.resize(v, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

            # Stronger CLAHE for contrast
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            v_eq = clahe.apply(v)

            # Unsharp mask
            blur = cv2.GaussianBlur(v_eq, (0, 0), 1.2)
            sharp = cv2.addWeighted(v_eq, 1.6, blur, -0.6, 0)

            # OTSU threshold
            _, thr = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # Light morphology open to suppress dots
            try:
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                proc = cv2.morphologyEx(thr, cv2.MORPH_OPEN, kernel, iterations=1)
            except Exception:
                proc = thr

            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"preprocessed_ktp2_{os.path.basename(image_path)}")
            cv2.imwrite(output_path, proc)
            return output_path
        except Exception as e:
            logger.error(f"KTP fallback2 preprocessing failed: {str(e)}")
            return image_path

    def extract_text(self, image_path: str, doc_type: Optional[str] = None, out_items: Optional[list] = None) -> Tuple[List[str], List[float]]:
        """Extract text from image with enhanced error handling"""
        text_lines = []
        confidences = []
        
        try:
            stage_used = "primary"
            dt = (doc_type or "").upper()
            # Configure timeout and retries, higher baseline to reduce CPU timeouts
            per_attempt_timeout = 20.0
            max_attempts = 2
            if dt == 'KTP':
                per_attempt_timeout = 22.0
                max_attempts = 3
            if PADDLEOCR_V3:
                # v6 medium models on CPU need ~30s for full-page documents;
                # a timeout here silently degrades to destructive fallbacks
                per_attempt_timeout = 90.0
            
            # Preprocess the image (primary)
            processed_path = self.preprocess_image(image_path, doc_type=doc_type)

            # Local helpers
            def _do_ocr(p: str):
                return self.run_ocr(p)

            def _quick_score(res, doc_t: str) -> Tuple[int, float]:
                try:
                    if not res or not res[0]:
                        return 0, 0.0
                    min_conf_local = 0.25
                    if doc_t in {"STNK", "KIR"}:
                        min_conf_local = 0.20
                    elif doc_t == "KTP":
                        min_conf_local = 0.22
                    # dict style
                    if isinstance(res[0], dict):
                        d = res[0]
                        texts = d.get('rec_texts') or []
                        scores = d.get('rec_scores') or [0.9] * len(texts)
                        kept = [float(s) for s in scores if (isinstance(s, (int, float)) and float(s) > min_conf_local)]
                        if not kept:
                            return 0, 0.0
                        return len(kept), sum(kept) / len(kept)
                    # list style
                    count = 0
                    total = 0.0
                    for line in res[0]:
                        conf = None
                        try:
                            if isinstance(line, (list, tuple)) and len(line) >= 2:
                                cand = line[1]
                                if isinstance(cand, (list, tuple)) and len(cand) >= 2 and isinstance(cand[1], (int, float)):
                                    conf = float(cand[1])
                                elif isinstance(cand, dict):
                                    v = cand.get('score') or cand.get('confidence')
                                    if isinstance(v, (int, float)):
                                        conf = float(v)
                                elif isinstance(cand, (int, float)):
                                    conf = float(cand)
                            # fallback default
                            if conf is None:
                                conf = 0.9
                        except Exception:
                            conf = 0.0
                        if conf > min_conf_local:
                            count += 1
                            total += conf
                    if count == 0:
                        return 0, 0.0
                    return count, total / count
                except Exception:
                    return 0, 0.0

            # Try the ORIGINAL image FIRST. PaddleOCR normalizes input
            # internally; the aggressive binarization/CLAHE pipelines below
            # measurably DESTROY real-world photos (verified on the KYC eval
            # set: raw image read a KTP NIK exactly while every preprocessed
            # variant produced digit soup). Preprocessing is now fallback-only.
            ocr_start_time = time.time()
            orig_result = None
            try:
                with _ocr_worker() as executor:
                    future = executor.submit(_do_ocr, image_path)
                    orig_result = future.result(timeout=per_attempt_timeout)
            except FuturesTimeout:
                logger.warning("OCR original-first timed out")
            except Exception as e:
                msg = str(e)
                logger.warning("OCR original-first error: %s", msg)
                if (('cudnn' in msg.lower() or 'cuda' in msg.lower())
                        and self._device == 'gpu' and not self._switched_to_cpu):
                    try:
                        self._reinit_ocr(self.lang, 'cpu')
                        self._switched_to_cpu = True
                        with _ocr_worker() as executor:
                            future = executor.submit(_do_ocr, image_path)
                            orig_result = future.result(timeout=per_attempt_timeout)
                    except Exception:
                        orig_result = None
            c_orig, avg_orig = _quick_score(orig_result, dt)
            logger.info("Original-first OCR quick score | doc_type=%s | lines=%d | avg=%.2f", dt, c_orig, avg_orig)

            result = None
            if c_orig >= 8 and avg_orig >= 0.60:
                result = orig_result
                stage_used = "original_first"

            # Run OCR on primary processed image with retries/timeouts
            # (only when the original image did not read well)
            attempt = 0
            last_exc: Optional[Exception] = None
            while result is None and attempt < max_attempts:
                attempt += 1
                try:
                    with _ocr_worker() as executor:
                        future = executor.submit(_do_ocr, processed_path)
                        result = future.result(timeout=per_attempt_timeout)
                    break
                except FuturesTimeout as te:
                    last_exc = te
                    logger.warning("OCR timed out (attempt %d)", attempt)
                    if attempt < max_attempts:
                        time.sleep(0.1 + random.random() * 0.2)
                        continue
                    else:
                        raise TimeoutError("PaddleOCR ocr() timed out")
                except Exception as e:
                    last_exc = e
                    msg = str(e)
                    logger.warning("OCR error on attempt %d: %s", attempt, msg)
                    # If GPU/cuDNN not configured, auto-switch to CPU once and retry
                    if (('cudnn' in msg.lower() or 'cudnn64_8.dll' in msg.lower() or 'cuda' in msg.lower())
                        and self._device == 'gpu' and not self._switched_to_cpu):
                        try:
                            self._reinit_ocr(self.lang, 'cpu')
                            self._switched_to_cpu = True
                            # Retry current attempt immediately on CPU
                            time.sleep(0.05)
                            continue
                        except Exception:
                            pass
                    if attempt < max_attempts:
                        time.sleep(0.1 + random.random() * 0.2)
                        continue
                    else:
                        raise
            
            # Evaluate primary result quality
            c_primary, avg_primary = _quick_score(result, dt)
            low_primary = (c_primary < 6) or (avg_primary < 0.35)
            logger.info(
                "Primary OCR quick score | doc_type=%s | lines=%d | avg=%.2f | low=%s",
                dt, c_primary, avg_primary, str(low_primary)
            )

            if not result or not result[0]:
                # Try alternative preprocessing once
                logger.info("No OCR result after primary preprocess; trying alt preprocess (doc_type=%s)", (doc_type or '').upper())
                alt_path = self.preprocess_image_alt(image_path, doc_type=doc_type)
                try:
                    with _ocr_worker() as executor:
                        future = executor.submit(_do_ocr, alt_path)
                        result = future.result(timeout=per_attempt_timeout)
                    stage_used = "alt"
                except Exception as e:
                    logger.warning("OCR alt-preprocess error: %s", str(e))
                    result = None
                c_alt, avg_alt = _quick_score(result, dt)
                logger.info(
                    "Alt OCR quick score | doc_type=%s | lines=%d | avg=%.2f | empty=%s",
                    dt, c_alt, avg_alt, str((not result) or (not result[0]))
                )
            elif dt in {"SIM", "STNK", "KIR"} and low_primary:
                # Primary produced low-value text; try doc-specific fallback2 directly
                if dt == "SIM":
                    logger.info("Low text after primary; trying SIM fallback2 pipeline")
                    sim2_path = self.preprocess_image_sim_fallback2(image_path)
                    try:
                        with _ocr_worker() as executor:
                            future = executor.submit(_do_ocr, sim2_path)
                            result = future.result(timeout=per_attempt_timeout)
                        stage_used = "sim_fallback2_lowtext"
                    except Exception as e:
                        logger.warning("OCR SIM-fallback2 error: %s", str(e))
                        result = None
                    c_sim2, avg_sim2 = _quick_score(result, dt)
                    logger.info(
                        "SIM fallback2 quick score | lines=%d | avg=%.2f | empty=%s",
                        c_sim2, avg_sim2, str((not result) or (not result[0]))
                    )
                else:
                    logger.info("Low text after primary; trying STNK/KIR fallback2 pipeline")
                    sk2_path = self.preprocess_image_stnk_kir_fallback2(image_path)
                    try:
                        with _ocr_worker() as executor:
                            future = executor.submit(_do_ocr, sk2_path)
                            result = future.result(timeout=per_attempt_timeout)
                        stage_used = "stnk_kir_fallback2_lowtext"
                    except Exception as e:
                        logger.warning("OCR STNK/KIR-fallback2 error: %s", str(e))
                        result = None
                    c_sk2, avg_sk2 = _quick_score(result, dt)
                    logger.info(
                        "STNK/KIR fallback2 quick score | lines=%d | avg=%.2f | empty=%s",
                        c_sk2, avg_sk2, str((not result) or (not result[0]))
                    )

            # KTP-specific second fallback before trying original image
            # Re-evaluate after alt/lowtext fallback
            c_mid, avg_mid = _quick_score(result, dt)
            low_mid = (c_mid < 6) or (avg_mid < 0.35)

            if ((not result) or (not result[0])) and dt == 'KTP':
                logger.info("No OCR result after alt preprocess; trying KTP fallback2 pipeline")
                ktp2_path = self.preprocess_image_ktp_fallback2(image_path)
                try:
                    with _ocr_worker() as executor:
                        future = executor.submit(_do_ocr, ktp2_path)
                        result = future.result(timeout=per_attempt_timeout)
                    stage_used = "ktp_fallback2"
                except Exception as e:
                    logger.warning("OCR KTP-fallback2 error: %s", str(e))
                    result = None

            # SIM aggressive second fallback (also when mid remains low)
            if (dt == 'SIM') and (((not result) or (not result[0])) or low_mid):
                logger.info("No/low OCR result after alt; trying SIM fallback2 pipeline")
                sim2_path = self.preprocess_image_sim_fallback2(image_path)
                try:
                    with _ocr_worker() as executor:
                        future = executor.submit(_do_ocr, sim2_path)
                        result = future.result(timeout=per_attempt_timeout)
                    if stage_used == "none":
                        stage_used = "sim_fallback2"
                except Exception as e:
                    logger.warning("OCR SIM-fallback2 error: %s", str(e))
                    result = None

                # Score the fallback2 result before comparing alternatives
                c_sim_mid, avg_sim_mid = _quick_score(result, dt)

                # Try denoise-alt branch and compare via quick-score
                try:
                    sim_dn_path = self.preprocess_image_sim_denoise_alt(image_path)
                    with _ocr_worker() as executor:
                        future = executor.submit(_do_ocr, sim_dn_path)
                        r_dn = future.result(timeout=per_attempt_timeout)
                    c_dn, avg_dn = _quick_score(r_dn, dt)
                    logger.info("SIM denoise-alt quick score | lines=%d | avg=%.2f", c_dn, avg_dn)
                    # Choose better mid-result
                    if c_dn > c_sim_mid or avg_dn > avg_sim_mid:
                        result = r_dn
                        stage_used = "sim_denoise_alt"
                        c_sim_mid, avg_sim_mid = c_dn, avg_dn
                except Exception as e:
                    logger.warning("OCR SIM-denoise-alt error: %s", str(e))

                # If still empty/low, try micro-rotation sweep
                c_sim_mid, avg_sim_mid = _quick_score(result, dt)
                if (((not result) or (not result[0])) or (c_sim_mid < 6) or (avg_sim_mid < 0.35)):
                    logger.info("SIM still low/empty after fallback2; trying micro-rotation sweep (-4..+4 deg, skip 0)")
                    rot_candidates = []
                    try:
                        angles = (-4.0, -3.0, -2.0, -1.0, 1.0, 2.0, 3.0, 4.0)
                        rot_candidates = [self._rotate_image_temp(image_path, a) for a in angles]
                    except Exception:
                        rot_candidates = []
                    for idx, rp in enumerate(rot_candidates):
                        try:
                            with _ocr_worker() as executor:
                                future = executor.submit(_do_ocr, rp)
                                r_res = future.result(timeout=per_attempt_timeout)
                            c_tmp, avg_tmp = _quick_score(r_res, dt)
                            logger.info("SIM rotated candidate %d quick score | lines=%d | avg=%.2f", idx, c_tmp, avg_tmp)
                            if c_tmp > c_sim_mid or avg_tmp > avg_sim_mid:
                                result = r_res
                                stage_used = f"sim_rot_candidate_{idx}"
                                c_sim_mid, avg_sim_mid = c_tmp, avg_tmp
                        except Exception as e:
                            logger.warning("OCR SIM-rotated error: %s", str(e))

            # STNK/KIR aggressive second fallback (also when mid remains low)
            if (dt in {'STNK', 'KIR'}) and (((not result) or (not result[0])) or low_mid):
                logger.info("No/low OCR result after alt; trying STNK/KIR fallback2 pipeline")
                sk2_path = self.preprocess_image_stnk_kir_fallback2(image_path)
                try:
                    with _ocr_worker() as executor:
                        future = executor.submit(_do_ocr, sk2_path)
                        result = future.result(timeout=per_attempt_timeout)
                    if stage_used == "none":
                        stage_used = "stnk_kir_fallback2"
                except Exception as e:
                    logger.warning("OCR STNK/KIR-fallback2 error: %s", str(e))
                    result = None
                c_sk2b, avg_sk2b = _quick_score(result, dt)
                logger.info(
                    "STNK/KIR fallback2 (phase2) quick score | lines=%d | avg=%.2f | empty=%s",
                    c_sk2b, avg_sk2b, str((not result) or (not result[0]))
                )

            # KIR-specific fallback3 if still empty/low after SK2
            if dt == 'KIR' and (((not result) or (not result[0])) or low_mid):
                logger.info("KIR still low/empty; trying KIR fallback3 pipeline")
                kir3_path = self.preprocess_image_kir_fallback3(image_path)
                try:
                    with _ocr_worker() as executor:
                        future = executor.submit(_do_ocr, kir3_path)
                        result = future.result(timeout=per_attempt_timeout)
                    stage_used = "kir_fallback3_lowtext"
                except Exception as e:
                    logger.warning("OCR KIR-fallback3 error: %s", str(e))
                    result = None
                c_kir3, avg_kir3 = _quick_score(result, dt)
                logger.info(
                    "KIR fallback3 quick score | lines=%d | avg=%.2f | empty=%s",
                    c_kir3, avg_kir3, str((not result) or (not result[0]))
                )

            # If no preprocessed variant beat the original-image read, keep
            # the original (it was only rejected for being below the
            # acceptance threshold, but it may still be the best available)
            if orig_result is not None and stage_used != "original_first":
                c_fin, avg_fin = _quick_score(result, dt)
                if c_orig > c_fin or (c_orig == c_fin and avg_orig > avg_fin):
                    result = orig_result
                    stage_used = "original_preferred"

            # Final fallback: try original image without preprocessing
            if not result or not result[0]:
                try:
                    with _ocr_worker() as executor:
                        future = executor.submit(_do_ocr, image_path)
                        result = future.result(timeout=per_attempt_timeout)
                    stage_used = "original"
                except Exception as e:
                    logger.warning("OCR original-image error: %s", str(e))
                    result = None

            # Mirror rescue: mirrored uploads (front camera, scan through
            # glass) read as almost nothing — measured 0/20 detection on the
            # robustness eval. If the best result is near-empty, try the
            # horizontally flipped image once and keep it when clearly better.
            c_pre_mirror, avg_pre_mirror = _quick_score(result, dt)
            # Trigger on few lines OR suspiciously low average confidence:
            # measured on real photos, normal reads avg ~0.97 while mirrored
            # reads avg ~0.75-0.80 with similar line counts
            if c_pre_mirror < 6 or avg_pre_mirror < 0.90:
                try:
                    img_m = cv2.imread(image_path)
                    if img_m is not None:
                        flipped = cv2.flip(img_m, 1)
                        fd_m, mirror_path = tempfile.mkstemp(suffix=".png")
                        os.close(fd_m)
                        cv2.imwrite(mirror_path, flipped)
                        with _ocr_worker() as executor:
                            future = executor.submit(_do_ocr, mirror_path)
                            r_m = future.result(timeout=per_attempt_timeout)
                        c_m, avg_m = _quick_score(r_m, dt)
                        # accept only on clear confidence improvement with
                        # comparable line count (flip of a legit photo reads
                        # WORSE, so this cannot swap a good result away)
                        if c_m > 0 and avg_m > avg_pre_mirror + 0.05 and c_m >= max(1, int(0.7 * c_pre_mirror)):
                            result = r_m
                            stage_used = "mirror_rescue"
                            logger.info("Mirror rescue succeeded | lines=%d avg=%.2f (was %d/%.2f)",
                                        c_m, avg_m, c_pre_mirror, avg_pre_mirror)
                except Exception as e:
                    logger.warning("Mirror rescue error: %s", str(e))

            if not result or not result[0]:
                logger.warning("No text detected after all preprocessing attempts | stage=%s | doc_type=%s",
                               stage_used, dt)
                return [], []
            
            # If modern dict-style output
            # Slightly relax KTP threshold; keep lower for STNK/KIR
            if dt in {"STNK", "KIR"}:
                min_conf = 0.20
            elif dt == "KTP":
                min_conf = 0.22
            else:
                min_conf = 0.25
            if isinstance(result[0], dict):
                d = result[0]
                rec_texts = d.get('rec_texts') or []
                rec_scores = d.get('rec_scores') or [0.9] * len(rec_texts)
                try:
                    for t, s in zip(rec_texts, rec_scores):
                        if t is None:
                            continue
                        try:
                            s_val = float(s)
                        except Exception:
                            s_val = 0.9
                        if s_val > min_conf:
                            text_lines.append(str(t).strip())
                            confidences.append(s_val)
                except Exception:
                    # Fall back to generic parsing if unexpected structure
                    pass
            else:
                # Process results (handle multiple possible output shapes across PaddleOCR versions)
                for line in result[0]:
                    text = None
                    confidence = None

                    try:
                        # Common shape: [bbox, (text, conf)]
                        if isinstance(line, (list, tuple)) and len(line) >= 2:
                            candidate = line[1]
                            if isinstance(candidate, (list, tuple)) and len(candidate) >= 2:
                                text = candidate[0]
                                confidence = float(candidate[1])
                            elif isinstance(candidate, str):
                                # Some versions may return [bbox, text]
                                text = candidate
                                confidence = 0.9
                            elif isinstance(candidate, dict):
                                # Rare dict-based formats
                                text = candidate.get('text') or candidate.get('label')
                                confidence = float(candidate.get('score') or candidate.get('confidence') or 0.9)
                        # Another observed shape: [text, conf]
                        if text is None and isinstance(line, (list, tuple)) and len(line) >= 2 and isinstance(line[0], str):
                            text = line[0]
                            try:
                                confidence = float(line[1])
                            except Exception:
                                confidence = 0.9
                        # Fallback: if line itself is a str
                        if text is None and isinstance(line, str):
                            text = line
                            confidence = 0.9
                    except Exception:
                        # Swallow and skip this line if unparsable
                        text = None
                        confidence = None

                    if text:
                        # Default confidence if missing
                        if confidence is None:
                            confidence = 0.9
                        if confidence > min_conf:
                            text_lines.append(str(text).strip())
                            confidences.append(confidence)
                            # expose line geometry for spatial pairing
                            if out_items is not None:
                                poly = line[0] if isinstance(line, (list, tuple)) and not isinstance(line[0], str) else None
                                try:
                                    xs = [float(pt[0]) for pt in poly]
                                    ys = [float(pt[1]) for pt in poly]
                                    out_items.append({
                                        "text": str(text).strip(), "conf": confidence,
                                        "x0": min(xs), "x1": max(xs),
                                        "cy": (min(ys) + max(ys)) / 2.0,
                                        "h": max(ys) - min(ys),
                                    })
                                except (TypeError, ValueError, IndexError):
                                    pass
            
            ocr_elapsed = time.time() - ocr_start_time
            logger.info(
                "OCR completed in %.3fs with %d lines (avg conf=%.2f) [stage=%s, doc_type=%s]",
                ocr_elapsed,
                len(text_lines),
                (sum(confidences) / len(confidences)) if confidences else 0.0,
                stage_used,
                dt,
            )
            return text_lines, confidences
            
        except Exception as e:
            logger.error(f"OCR processing failed: {str(e)}", exc_info=True)
            return [], []
            
        finally:
            # Clean up temporary files
            try:
                # Skip cleanup if debug-save is enabled
                if not getattr(self, 'debug_save', False):
                    if 'processed_path' in locals() and processed_path != image_path and os.path.exists(processed_path):
                        os.remove(processed_path)
                    if 'alt_path' in locals() and alt_path != image_path and os.path.exists(alt_path):
                        os.remove(alt_path)
                    if 'ktp2_path' in locals() and ktp2_path != image_path and os.path.exists(ktp2_path):
                        os.remove(ktp2_path)
                    if 'sim2_path' in locals() and sim2_path != image_path and os.path.exists(sim2_path):
                        os.remove(sim2_path)
                    if 'sim_dn_path' in locals() and sim_dn_path != image_path and os.path.exists(sim_dn_path):
                        os.remove(sim_dn_path)
                    if 'sk2_path' in locals() and sk2_path != image_path and os.path.exists(sk2_path):
                        os.remove(sk2_path)
                    if 'kir3_path' in locals() and kir3_path != image_path and os.path.exists(kir3_path):
                        os.remove(kir3_path)
                    if 'mirror_path' in locals() and os.path.exists(mirror_path):
                        os.remove(mirror_path)
                    if 'rot_candidates' in locals():
                        for rp in rot_candidates:
                            try:
                                if rp != image_path and os.path.exists(rp):
                                    os.remove(rp)
                            except Exception:
                                pass
            except Exception as e:
                logger.warning(f"Failed to clean up temporary file: {str(e)}")

    def preprocess_image_stnk_kir_fallback2(self, image_path: str) -> str:
        """Aggressive fallback for STNK/KIR.
        - Use HSV V channel
        - Strong CLAHE + optional denoise + unsharp mask
        - OTSU binarization combined with Adaptive Gaussian
        - Morphological close then light open
        - Upscale more for small/medium images
        """
        try:
            img = cv2.imread(image_path)
            if img is None:
                raise ValueError(f"Failed to read image: {image_path}")

            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            v = hsv[:, :, 2]

            # Upscale more aggressively for small/medium images
            h, w = v.shape
            if max(h, w) < 1600:
                scale = 2.1  # ~2.0–2.2x
                v = cv2.resize(v, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

            # Stronger CLAHE
            clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
            v_eq = clahe.apply(v)

            # Optional fast denoise for compression artifacts (grayscale variant)
            try:
                v_dn = cv2.fastNlMeansDenoising(v_eq, None, h=7, templateWindowSize=7, searchWindowSize=21)
            except Exception:
                v_dn = v_eq

            # Unsharp mask to enhance edges
            try:
                g = cv2.GaussianBlur(v_dn, (0, 0), sigmaX=1.2)
                v_sharp = cv2.addWeighted(v_dn, 1.6, g, -0.6, 0)
            except Exception:
                v_sharp = v_dn

            # OTSU binarization
            _, thr_otsu = cv2.threshold(v_sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # Adaptive Gaussian (helps non-uniform lighting)
            try:
                thr_adp = cv2.adaptiveThreshold(v_sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                cv2.THRESH_BINARY, 21, 9)
            except Exception:
                thr_adp = thr_otsu

            # Combine: keep foreground from either method
            try:
                thr = cv2.bitwise_or(thr_otsu, thr_adp)
            except Exception:
                thr = thr_otsu

            # Morphology: close then light open
            try:
                k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
                tmp = cv2.morphologyEx(thr, cv2.MORPH_CLOSE, k_close, iterations=1)
                k_open = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                proc = cv2.morphologyEx(tmp, cv2.MORPH_OPEN, k_open, iterations=1)
            except Exception:
                proc = thr

            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"preprocessed_sk2_{os.path.basename(image_path)}")
            cv2.imwrite(output_path, proc)
            return output_path
        except Exception as e:
            logger.error(f"STNK/KIR fallback2 preprocessing failed: {str(e)}")
            return image_path

    def preprocess_image_kir_fallback3(self, image_path: str) -> str:
        """KIR-specific aggressive fallback3.
        Focus: printed forms with noisy backgrounds and uneven illumination.
        Steps:
        - Convert to grayscale (prefer HSV V if color present)
        - Upscale to ~1800px on longer side for finer text
        - Morphological top-hat and black-hat to emphasize foreground text
        - CLAHE strong contrast
        - Strong unsharp mask
        - Combine OTSU and Adaptive Gaussian thresholds
        - Morphological close then light open
        """
        try:
            img = cv2.imread(image_path)
            if img is None:
                raise ValueError(f"Failed to read image: {image_path}")

            if len(img.shape) == 3:
                hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
                gray = hsv[:, :, 2]
            else:
                gray = img

            # Upscale to help recognition on small text
            h, w = gray.shape
            target_long = 1800
            if max(h, w) < target_long:
                scale = target_long / max(h, w)
                gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

            # Morphological top-hat and black-hat operations
            try:
                k = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
                tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k)
                blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k)
                enh = cv2.addWeighted(gray, 1.0, tophat, 1.0, 0)
                enh = cv2.subtract(enh, blackhat)
            except Exception:
                enh = gray

            # Strong CLAHE
            try:
                clahe = cv2.createCLAHE(clipLimit=3.8, tileGridSize=(8, 8))
                v_eq = clahe.apply(enh)
            except Exception:
                v_eq = enh

            # Strong unsharp mask
            try:
                g = cv2.GaussianBlur(v_eq, (0, 0), sigmaX=1.4)
                sharp = cv2.addWeighted(v_eq, 1.8, g, -0.8, 0)
            except Exception:
                sharp = v_eq

            # Mix OTSU and Adaptive
            try:
                _, thr_otsu = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            except Exception:
                thr_otsu = sharp
            try:
                thr_adp = cv2.adaptiveThreshold(sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                cv2.THRESH_BINARY, 23, 7)
            except Exception:
                thr_adp = thr_otsu
            try:
                thr = cv2.bitwise_or(thr_otsu, thr_adp)
            except Exception:
                thr = thr_otsu

            # Morphology: close to connect characters then light open
            try:
                k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
                tmp = cv2.morphologyEx(thr, cv2.MORPH_CLOSE, k_close, iterations=1)
                k_open = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                proc = cv2.morphologyEx(tmp, cv2.MORPH_OPEN, k_open, iterations=1)
            except Exception:
                proc = thr

            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"preprocessed_kir3_{os.path.basename(image_path)}")
            cv2.imwrite(output_path, proc)
            return output_path
        except Exception as e:
            logger.error(f"KIR fallback3 preprocessing failed: {str(e)}")
            return image_path

# Global instance
ocr_service = OCRService()

def extract_text_from_image(image_input: Union[str, bytes], doc_type: Optional[str] = None, return_items: bool = False):
    """
    Extract text from image using the enhanced OCR service.
    
    Args:
        image_input: Either a filesystem path to the image file (str) or raw image bytes
        
    Returns:
        List of extracted text lines
    """
    try:
        temp_path = None
        image_path: str

        # If bytes are provided, validate/normalize with cv2.imdecode before writing to disk
        if isinstance(image_input, (bytes, bytearray)):
            try:
                arr = np.frombuffer(image_input, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
            except Exception as e:
                logger.error("Failed to decode image bytes: %s", str(e))
                return ([], []) if return_items else []

            if img is None:
                logger.error("Decoded image is None (invalid/corrupted bytes)")
                return ([], []) if return_items else []

            # Normalize channels: drop alpha if present, ensure BGR
            try:
                if img.ndim == 2:
                    # grayscale -> keep as is
                    norm = img
                else:
                    if img.shape[2] == 4:
                        # BGRA/RGBA -> BGR
                        try:
                            norm = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                        except Exception:
                            norm = img[:, :, :3]
                    elif img.shape[2] == 3:
                        norm = img
                    else:
                        # Unexpected number of channels; convert to BGR by best effort
                        norm = cv2.cvtColor(img, cv2.COLOR_BGR2RGB) if img.shape[2] >= 3 else img
            except Exception:
                norm = img

            # Upscale very small images to aid OCR
            try:
                h, w = norm.shape[:2]
                long_side = max(h, w)
                if long_side < 800:
                    target = 1000
                    scale = float(target) / float(long_side)
                    new_w, new_h = int(w * scale), int(h * scale)
                    norm = cv2.resize(norm, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            except Exception:
                pass

            # Write normalized PNG to a temp file
            fd, temp_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            try:
                ok, enc = cv2.imencode('.png', norm)
                if not ok:
                    logger.error("Failed to encode normalized image to PNG")
                    return ([], []) if return_items else []
                with open(temp_path, 'wb') as f:
                    f.write(enc.tobytes())
            except Exception as e:
                logger.error("Failed to write normalized image to temp file: %s", str(e))
                return ([], []) if return_items else []
            image_path = temp_path

        elif isinstance(image_input, str):
            # Validate path and basic readability to avoid NoneType in downstream preproc
            if not os.path.exists(image_input):
                logger.error("Image path does not exist: %s", image_input)
                return ([], []) if return_items else []
            try:
                probe = cv2.imread(image_input)
            except Exception as e:
                logger.error("cv2.imread raised for path %s: %s", image_input, str(e))
                return ([], []) if return_items else []
            if probe is None:
                logger.error("cv2.imread returned None for path: %s", image_input)
                return ([], []) if return_items else []
            image_path = image_input
        else:
            logger.error("Unsupported image_input type; expected str path or bytes")
            return ([], []) if return_items else []

        # Use the OCR service to extract text
        items: list = []
        text_lines, confidences = ocr_service.extract_text(image_path, doc_type=doc_type, out_items=items if return_items else None)

        if not text_lines:
            logger.warning("No text was extracted from the image")
            return ([], []) if return_items else []

        try:
            avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0
        except Exception:
            avg_conf = 0.0
        logger.info(
            "Extracted %d text lines with average confidence: %.2f",
            len(text_lines), avg_conf
        )

        return (text_lines, items) if return_items else text_lines

    except Exception as e:
        logger.error(f"Error in extract_text_from_image: {str(e)}", exc_info=True)
        return ([], []) if return_items else []
    finally:
        # Cleanup temporary file if we created one
        try:
            if 'temp_path' in locals() and temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as e:
            logger.warning(f"Failed to remove temporary image file: {str(e)}")