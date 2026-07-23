#!/usr/bin/env python3
"""Serialized OCR runner. Paddle CPU predictor is not thread-safe -> one at a time."""
import json, sys, time, pathlib, urllib.request, mimetypes, uuid

import os
PORT = os.environ.get("OCR_PORT", "8000")
API = f"http://localhost:{PORT}/api/v1/ocr/file"
OUT = pathlib.Path(__file__).parent / os.environ.get("OCR_OUT", "results")
OUT.mkdir(exist_ok=True)


def post_file(path: pathlib.Path, doc_type="AUTO"):
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode()
    body += f"Content-Type: {ctype}\r\n\r\n".encode()
    body += path.read_bytes() + b"\r\n"
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="document_type"\r\n\r\n'
    body += doc_type.encode() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        API, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def slug(p: pathlib.Path, root: pathlib.Path):
    # flatten the relative path into ONE filename; must collapse BOTH path
    # separators or Windows ("Driver License\\x.jpeg") writes into a
    # non-existent subdir and crashes
    parts = p.relative_to(root).parts
    return "__".join(parts).replace(" ", "_")


def wait_healthy(timeout=180):
    """The app process can die on a heavy page and be restarted by Docker."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://localhost:{PORT}/health", timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def main():
    root = pathlib.Path(sys.argv[1])
    files = sorted(
        p for p in root.rglob("*")
        if p.suffix.lower() in {".jpeg", ".jpg", ".png", ".webp", ".pdf"}
        and not p.name.startswith(".")
    )
    print(f"{len(files)} files\n", flush=True)
    for i, p in enumerate(files, 1):
        dest = OUT / (slug(p, root) + ".json")
        if dest.exists():
            try:  # only skip when the cache is VALID json (a crash mid-write isn't)
                json.loads(dest.read_text(encoding="utf-8"))
                print(f"[{i}/{len(files)}] skip (cached) {p.name}", flush=True)
                continue
            except (ValueError, OSError):
                pass
        res, err = None, None
        for attempt in range(3):
            if not wait_healthy():
                err = "server never came back healthy"
                break
            t = time.time()
            try:
                res = post_file(p)
                res["_source"] = str(p.relative_to(root))
                res["_elapsed"] = round(time.time() - t, 1)
                res["_attempts"] = attempt + 1
                break
            except Exception as e:
                # A heavy page can kill the app process mid-request; Docker restarts
                # it, so back off and retry rather than recording a phantom failure.
                err = f"{type(e).__name__}: {e}"
                print(f"    attempt {attempt+1} failed ({err}) - waiting for restart",
                      flush=True)
                time.sleep(10)

        if res is None:
            dest.write_text(json.dumps({"_source": str(p.relative_to(root)), "_error": err}),
                            encoding="utf-8")
            print(f"[{i}/{len(files)}] {p.name:45} ERROR {err}", flush=True)
            continue
        # encoding pinned: Windows default cp1252 cannot encode Indonesian text
        dest.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        n = len((res.get("data") or {}).get("fields") or {})
        sub = res.get("documents")
        extra = f" (MULTI:{len(sub)} subdocs)" if sub else ""
        print(f"[{i}/{len(files)}] {p.name:45} {str(res.get('document_type')):7} "
              f"{n:2} fields  {res['_elapsed']}s{extra}", flush=True)


if __name__ == "__main__":
    main()
