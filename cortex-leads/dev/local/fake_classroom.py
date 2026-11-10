"""A Google Classroom (and the bit of Drive it points at) that lives in memory (WP33). Tests use `FakeClassroom.transport()`;
`python -m dev.local.fake_classroom [port]` serves it over HTTP so the whole grader can be tried with
CL_CLASSROOM_API_BASE=http://127.0.0.1:8302/v1 and no Google account. It keeps Google's one rule that matters here: only course
work created through the API ("ours") may have its grades changed, else 403 PERMISSION_DENIED."""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

DOC = "application/vnd.google-apps.document"


def minimal_pdf(text: str | None) -> bytes:
    """A one-page PDF; with `text=None` the page is empty, as the text layer of a scan is."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            b"<</Length %d>>\nstream\n" % len(stream) + stream + b"\nendstream", b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)


class FakeClassroom:
    def __init__(self) -> None:
        self.courses: dict[str, dict] = {"c1": {"id": "c1", "name": "Tiếng Anh A1", "courseState": "ACTIVE"}}
        self.students: dict[str, dict] = {}
        self.work: dict[str, dict] = {}          # id -> courseWork resource (+ "_course")
        self.subs: dict[str, dict] = {}          # id -> studentSubmission resource (+ "_work")
        self.files: dict[str, dict] = {}         # drive id -> {"mimeType", "text"}
        self.calls: list[tuple[str, str]] = []
        self.folders: dict[str, dict] = {}        # created through files.create
        self.uploaded: dict[str, dict] = {}       # id -> {"name", "parents", "bytes": bytearray, "mime"}
        self.trashed: set[str] = set()             # files moved to the bin
        self.announcements: dict[str, dict] = {}   # what was posted to a course's stream
        self.topics: dict[str, dict] = {}          # topicId -> {"topicId", "name", "_course"}
        self.deleted_work: set[str] = set()        # course work removed through the API
        self._sessions: dict[str, dict] = {}
        self.write_refused_in: str | None = None  # a folder id in which new files are refused, like a narrow sign-in in a folder it did not make
        self.drive_refuses: str | None = None     # "storage" | "scope" | "auth": make the next uploads fail like Google would
        self.course_refuses = False               # a teacher Google does not let make courses: creating one is 403
        self.activate_refuses = False             # an account Google lets create a course but not move it to ACTIVE
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    # -- seeding -----------------------------------------------------------------------------
    def add_student(self, user_id: str, name: str) -> None:
        self.students[user_id] = {"userId": user_id, "profile": {"name": {"fullName": name}}}

    def add_work(self, title: str, *, max_points: int = 10, ours: bool = False, description: str = "", course: str = "c1") -> str:
        wid = self._id("w")
        self.work[wid] = {"id": wid, "title": title, "description": description, "maxPoints": max_points, "state": "PUBLISHED",
                          "workType": "ASSIGNMENT", "associatedWithDeveloper": ours, "_course": course}
        return wid

    def add_submission(self, work_id: str, user_id: str, *, answer: str | None = None, doc: str | None = None,
                       state: str = "TURNED_IN", file: tuple[str, bytes, str] | None = None) -> str:
        """`doc`: a Google Doc with that text. `file`: (mime type, bytes, title) of an uploaded file: a PDF, a Word file, a recording."""
        sid = self._id("s")
        course = self.work[work_id]["_course"]
        sub: dict[str, Any] = {"id": sid, "userId": user_id, "state": state, "updateTime": "2026-10-22T08:00:00Z", "_work": work_id,
                               "alternateLink": f"https://classroom.google.com/c/{course}/a/{work_id}/submissions/by-status/and-sort-name/all"}
        if answer is not None:
            sub["shortAnswerSubmission"] = {"answer": answer}
        if doc is not None or file is not None:
            fid = self._id("f")
            self.files[fid] = ({"mimeType": file[0], "bytes": file[1], "text": ""} if file else {"mimeType": DOC, "text": doc or ""})
            sub["assignmentSubmission"] = {"attachments": [{"driveFile": {"id": fid, "title": file[2] if file else "Bài làm"}}]}
        self.subs[sid] = sub
        return sid

    # -- the API -----------------------------------------------------------------------------
    def _json(self, status: int, body: Any) -> httpx.Response:
        return httpx.Response(status, json=body)

    def handle(self, req: httpx.Request) -> httpx.Response:
        url = urlsplit(str(req.url))
        path, q = url.path, parse_qs(url.query)
        self.calls.append((req.method, path + (f"?{url.query}" if url.query else "")))
        if path == "/token":  # the OAuth token endpoint: any refresh token is good here, it is a stand-in
            return self._json(200, {"access_token": "fake-token", "expires_in": 3600})
        if "Authorization" not in req.headers:
            return self._json(401, {"error": {"status": "UNAUTHENTICATED"}})
        try:
            body = json.loads(req.content) if req.content else {}
        except ValueError:  # an uploaded chunk is bytes, not JSON
            body = {}
        if path == "/upload/drive/v3/files" and req.method == "POST":  # start of a resumable upload
            refused = self._drive_refusal()
            if refused:
                return refused
            meta = json.loads(req.content or b"{}")
            sid = self._id("session")
            self._sessions[sid] = {"meta": meta, "bytes": bytearray(), "total": int(req.headers.get("x-upload-content-length", 0)), "origin": req.headers.get("origin")}
            return httpx.Response(200, headers={"location": f"http://fake.drive/upload/session/{sid}"}, json={})
        if (m := re.fullmatch(r"/upload/session/(\w+)", path)) and req.method == "PUT":
            sid = m[1]
            sess = self._sessions.get(sid)
            if sess is None:
                return self._json(404, {})
            sess["bytes"] += req.content
            if len(sess["bytes"]) < sess["total"]:
                return httpx.Response(308, headers={"range": f"bytes=0-{len(sess['bytes']) - 1}"})
            fid = self._id("up")
            self.uploaded[fid] = {"name": sess["meta"].get("name"), "parents": sess["meta"].get("parents"), "bytes": sess["bytes"], "mime": sess["meta"].get("mimeType")}
            return self._json(200, {"id": fid, "webViewLink": f"https://drive.google.com/file/d/{fid}/view"})
        if path == "/drive/v3/files" and req.method == "POST":  # files.create: a folder
            refused = self._drive_refusal()
            if refused:
                return refused
            body = json.loads(req.content or b"{}")
            if body.get("mimeType") == "text/plain":  # check_write: a tiny file in a folder
                if self.write_refused_in and self.write_refused_in in (body.get("parents") or []):
                    return self._json(404, {"error": {"status": "NOT_FOUND"}})
                fid = self._id("probe")
                self.uploaded[fid] = {"name": body.get("name"), "parents": body.get("parents"), "bytes": bytearray(), "mime": "text/plain"}
                return self._json(200, {"id": fid})
            fid = self._id("folder")
            self.folders[fid] = {"id": fid, **body, "trashed": False}
            return self._json(200, {"id": fid})
        if (m := re.fullmatch(r"/drive/v3/files/(\w+)", path)) and req.method == "DELETE":
            self.uploaded.pop(m[1], None)
            return httpx.Response(204)
        if (m := re.fullmatch(r"/drive/v3/files/(\w+)", path)) and req.method == "PATCH":
            if m[1] not in self.files and m[1] not in self.uploaded:
                return self._json(404, {})
            self.trashed.add(m[1])
            return self._json(200, {"id": m[1]})
        if m := re.fullmatch(r"/drive/v3/files/(\w+)(/export)?", path):
            if m[1] in self.folders:
                return self._json(200, {"id": m[1], "trashed": self.folders[m[1]]["trashed"]})
            f = self.files.get(m[1])
            if f is None and m[1] in self.uploaded:  # something Cortex put there: readable like any file
                u = self.uploaded[m[1]]
                f = {"mimeType": u["mime"] or "application/octet-stream", "bytes": bytes(u["bytes"])}
            if f is None:
                return self._json(404, {})
            if q.get("alt") == ["media"]:
                body_bytes = f["bytes"] if "bytes" in f else f["text"].encode()
                if (rng := req.headers.get("range")) is not None:
                    a, _, b = rng.removeprefix("bytes=").partition("-")
                    start = int(a) if a else max(len(body_bytes) - int(b), 0)
                    end = min(int(b), len(body_bytes) - 1) if a and b else len(body_bytes) - 1
                    if start >= len(body_bytes):
                        return self._json(416, {})
                    return httpx.Response(206, content=body_bytes[start:end + 1], headers={"content-range": f"bytes {start}-{end}/{len(body_bytes)}"})
                return httpx.Response(200, content=body_bytes)
            if q.get("fields"):
                return self._json(200, {"mimeType": f["mimeType"], "size": str(len(f["bytes"]) if "bytes" in f else len(f["text"]))})
            return httpx.Response(200, content=f["bytes"]) if "bytes" in f else httpx.Response(200, text=f["text"])
        if path == "/v1/courses" and req.method == "POST":
            if self.course_refuses:
                return self._json(403, {"error": {"status": "PERMISSION_DENIED"}})
            if body.get("courseState") == "ACTIVE":  # what Google does to a teacher who is not an admin: the state may not be asked for on create
                return self._json(403, {"error": {"status": "PERMISSION_DENIED", "message": "@CourseStateDenied"}})
            cid = self._id("nc")
            self.courses[cid] = {"id": cid, "name": body.get("name", ""), "courseState": "PROVISIONED", "ownerId": body.get("ownerId"),
                                 "alternateLink": f"https://classroom.google.com/c/{cid}"}
            return self._json(200, self.courses[cid])
        if path == "/v1/courses":
            return self._json(200, {"courses": list(self.courses.values())})
        if (m := re.fullmatch(r"/v1/courses/(\w+)", path)) and req.method == "PATCH":
            c = self.courses.get(m[1])
            if c is None:
                return self._json(404, {})
            if self.activate_refuses:
                return self._json(403, {"error": {"status": "PERMISSION_DENIED", "message": "@CourseStateDenied"}})
            c.update(body)
            return self._json(200, c)
        if m := re.fullmatch(r"/v1/courses/(\w+)", path):
            c = self.courses.get(m[1])
            return self._json(200, c) if c else self._json(404, {})
        if m := re.fullmatch(r"/v1/courses/(\w+)/announcements", path):
            if m[1] not in self.courses:
                return self._json(404, {})
            aid = self._id("a")
            self.announcements[aid] = {"id": aid, "courseId": m[1], "text": body.get("text", ""), "state": body.get("state", "PUBLISHED")}
            return self._json(200, self.announcements[aid])
        if m := re.fullmatch(r"/v1/courses/(\w+)/students/(\w+)", path):
            s = self.students.get(m[2])
            return self._json(200, s) if s else self._json(404, {})
        if m := re.fullmatch(r"/v1/courses/(\w+)/topics", path):
            if m[1] not in self.courses:
                return self._json(404, {})
            if req.method == "GET":
                return self._json(200, {"topic": [self._public(t) for t in self.topics.values() if t["_course"] == m[1]]})
            tid = self._id("t")
            self.topics[tid] = {"topicId": tid, "name": body.get("name", ""), "_course": m[1]}
            return self._json(200, self._public(self.topics[tid]))
        if m := re.fullmatch(r"/v1/courses/(\w+)/students", path):
            return self._json(200, {"students": list(self.students.values())})
        if m := re.fullmatch(r"/v1/courses/(\w+)/courseWork/(\w+)", path):
            work = self.work.get(m[2])
            if work is None or work["_course"] != m[1]:
                return self._json(404, {})
            if req.method == "GET":
                return self._json(200, self._public(work))
            if not work["associatedWithDeveloper"]:  # Google: only the project that made the work may change or delete it
                return self._json(403, {"error": {"status": "PERMISSION_DENIED"}})
            if req.method == "DELETE":
                del self.work[m[2]]
                self.deleted_work.add(m[2])
                return self._json(200, {})
            mask = q.get("updateMask", [""])[0].split(",")
            allowed = {"title", "description", "state", "dueDate", "dueTime", "maxPoints", "scheduledTime", "topicId"}  # NOT materials
            if not mask or any(f not in allowed for f in mask):
                return self._json(400, {"error": {"status": "INVALID_ARGUMENT"}})
            if "state" in mask and (work["state"] != "DRAFT" or body.get("state") != "PUBLISHED"):
                return self._json(400, {"error": {"status": "INVALID_ARGUMENT"}})
            for f in mask:
                if f in body:
                    work[f] = body[f]
                else:
                    work.pop(f, None)
            if "state" in mask:
                work.pop("scheduledTime", None)
            return self._json(200, self._public(work))
        if m := re.fullmatch(r"/v1/courses/(\w+)/courseWork", path):
            if req.method == "GET":
                states = q.get("courseWorkStates", [])
                return self._json(200, {"courseWork": [self._public(w) for w in self.work.values()
                                                       if w["_course"] == m[1] and (not states or w["state"] in states)]})
            if m[1] not in self.courses:
                return self._json(404, {})
            if body.get("topicId") and body["topicId"] not in self.topics:
                return self._json(400, {"error": {"status": "INVALID_ARGUMENT"}})
            if body.get("scheduledTime") and body.get("state") != "DRAFT":  # Classroom: a schedule only goes with a draft
                return self._json(400, {"error": {"status": "INVALID_ARGUMENT"}})
            wid = self._id("w")
            self.work[wid] = {**{k: v for k, v in body.items()}, "id": wid, "associatedWithDeveloper": True, "_course": m[1],
                              "state": body.get("state", "PUBLISHED")}
            return self._json(200, self._public(self.work[wid]))
        if m := re.fullmatch(r"/v1/courses/(\w+)/courseWork/(\w+)/studentSubmissions", path):
            states = q.get("states", [])
            subs = [self._sub(s) for s in self.subs.values() if s["_work"] == m[2] and (not states or s["state"] in states)]
            return self._json(200, {"studentSubmissions": subs})
        if m := re.fullmatch(r"/v1/courses/(\w+)/courseWork/(\w+)/studentSubmissions/(\w+)(:return)?", path):
            work, sub = self.work.get(m[2]), self.subs.get(m[3])
            if work is None or sub is None:
                return self._json(404, {})
            if req.method == "GET":
                return self._json(200, self._sub(sub))
            if not work["associatedWithDeveloper"]:
                return self._json(403, {"error": {"status": "PERMISSION_DENIED"}})
            if m[4]:
                sub["state"] = "RETURNED"
                return self._json(200, {})
            mask = q.get("updateMask", [""])[0].split(",")
            if not mask or any(f not in ("draftGrade", "assignedGrade") for f in mask):
                return self._json(400, {"error": {"status": "INVALID_ARGUMENT"}})
            for f in mask:
                sub[f] = body.get(f)
            return self._json(200, self._sub(sub))
        return self._json(404, {})

    def _drive_refusal(self) -> httpx.Response | None:
        return {"storage": self._json(403, {"error": {"errors": [{"reason": "storageQuotaExceeded"}]}}),
                "scope": self._json(403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}}),
                "auth": self._json(401, {"error": {}})}.get(self.drive_refuses or "")

    @staticmethod
    def _public(w: dict) -> dict:
        return {k: v for k, v in w.items() if not k.startswith("_")}

    @staticmethod
    def _sub(s: dict) -> dict:
        return {k: v for k, v in s.items() if not k.startswith("_")}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


def demo() -> FakeClassroom:
    """A small class with one assignment of ours (grades can be written) and one the teacher made by hand (they cannot)."""
    fc = FakeClassroom()
    for uid, name in (("u1", "Nguyễn Minh An"), ("u2", "Trần Bảo Châu"), ("u3", "Lê Hoàng Dũng")):
        fc.add_student(uid, name)
    ours = fc.add_work("Viết 5 câu thì hiện tại hoàn thành", max_points=10, ours=True,
                       description="Viết 5 câu về bản thân dùng thì hiện tại hoàn thành (have/has + quá khứ phân từ).")
    fc.add_submission(ours, "u1", doc="I have lived in Hanoi for five years. She has finished her homework. We have never been to Paris. "
                                       "He has played football since morning. They have just arrived.")
    fc.add_submission(ours, "u2", doc="I live in Hanoi. She finish her homework. We never go to Paris yesterday. He plays football. They arrive.")
    fc.add_submission(ours, "u3", answer="I have eaten breakfast. My brother has gone to school.")
    manual = fc.add_work("Bài đọc tuần 5", max_points=5, ours=False)
    fc.add_submission(manual, "u1", answer="The text is about a boy who has a dog.")
    return fc


class _Handler(BaseHTTPRequestHandler):
    fake: FakeClassroom

    def _serve(self) -> None:
        n = int(self.headers.get("content-length", 0))
        req = httpx.Request(self.command, f"http://x{self.path}", headers=dict(self.headers), content=self.rfile.read(n) if n else b"")
        res = self.fake.handle(req)
        self.send_response(res.status_code)
        self.send_header("content-type", res.headers.get("content-type", "application/json"))
        self.end_headers()
        self.wfile.write(res.content)

    do_GET = do_POST = do_PATCH = do_DELETE = _serve

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    # python -m dev.local.fake_classroom [port] [--audio spoken.mp3]: the second adds a spoken answer, to try recordings
    args = sys.argv[1:]
    port = int(args[0]) if args and args[0].isdigit() else 8302
    _Handler.fake = demo()
    fc = _Handler.fake
    w1 = next(w for w in fc.work.values() if w["associatedWithDeveloper"])["id"]
    fc.add_student("u4", "Phạm Gia Bảo")
    fc.add_submission(w1, "u4", file=("application/pdf", minimal_pdf("I have never eaten sushi. She has visited Hue twice. We have lived here since 2020."), "Bài PDF.pdf"))
    if "--audio" in args:
        from pathlib import Path

        fc.add_student("u5", "Võ Thanh Hà")
        fc.add_submission(w1, "u5", file=("audio/mpeg", Path(args[args.index("--audio") + 1]).read_bytes(), "Bài nói.mp3"))
    print(f"Classroom giả: http://127.0.0.1:{port}/v1  (khoá học c1, 2 bài tập, 5 bài nộp, có một PDF)\n  CL_CLASSROOM_API_BASE=http://127.0.0.1:{port}/v1 CL_GOOGLE_TOKEN_URL=http://127.0.0.1:{port}/token CL_DRIVE_API_BASE=http://127.0.0.1:{port}/drive/v3", flush=True)
    HTTPServer(("127.0.0.1", port), _Handler).serve_forever()
