"""Google Classroom as the grader sees it (WP33): courses, course work, the submissions handed in, and the three things a teacher's
account can do back (create work, set a grade, return it). Read and write are kept apart on purpose: reading is for the AI's
suggestion, `create_coursework` and `set_grade` are called only by code a person's click has reached.
Google lets only the Cloud project that CREATED a piece of course work change its grades (PERMISSION_DENIED otherwise), so a
`CourseWork` says whether it is `ours`, and the write-back refuses anything that is not."""
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from cortex_leads.config import get_settings
from cortex_leads.connectors.google_auth import TokenSource
from cortex_leads.core.errors import CortexError
from cortex_leads.core.timefmt import wire

CLASSROOM_API = "https://classroom.googleapis.com/v1"
DRIVE_API = "https://www.googleapis.com/drive/v3"
SCOPES = ["https://www.googleapis.com/auth/classroom.courses.readonly",
          "https://www.googleapis.com/auth/classroom.coursework.students",
          "https://www.googleapis.com/auth/classroom.rosters.readonly",
          "https://www.googleapis.com/auth/drive.readonly"]  # reading what students attach: this sign-in is for GRADING only
POST_SCOPES = ["https://www.googleapis.com/auth/classroom.courses.readonly",
               "https://www.googleapis.com/auth/classroom.announcements"]  # a lesson recap posted to a course's stream: nothing else in Classroom is touched
COURSE_SCOPES = ["https://www.googleapis.com/auth/classroom.courses"]  # making a new course for a class: asked for on its own, so an account that only posts or grades cannot also create or change courses
TOPIC_SCOPES = ["https://www.googleapis.com/auth/classroom.topics"]  # filing a piece of work under a topic. Asked for along with grading but never REQUIRED (not in KINDS): an account connected before it keeps working, and only topics wait for a new sign-in
DRIVE_ONLY_SCOPES = ["https://www.googleapis.com/auth/drive.file"]  # a Drive target's sign-in: only what Cortex creates itself, nothing else in that Drive
PAGES = 20
EXPORTABLE = {"application/vnd.google-apps.document": "text/plain"}
ERRORS = {400: "INVALID_ARGUMENT", 401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND", 409: "ABORTED", 429: "RATE_LIMITED"}


class ClassroomError(CortexError):
    """`.code`: INVALID_ARGUMENT | UNAUTHENTICATED | PERMISSION_DENIED | NOT_FOUND | ABORTED | RATE_LIMITED | UPSTREAM | TOO_LARGE | NOT_OURS"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Attachment:
    kind: str  # drive | link | other
    id: str
    title: str


@dataclass(frozen=True)
class CourseWork:
    id: str
    course_id: str
    title: str
    description: str
    max_points: float | None
    state: str
    due: datetime | None
    ours: bool  # created by this app's Cloud project: the only course work whose grades we may write
    work_type: str = "ASSIGNMENT"
    topic_id: str | None = None
    scheduled: datetime | None = None  # a DRAFT with a time: Classroom publishes it itself then


@dataclass(frozen=True)
class Submission:
    id: str
    course_id: str
    coursework_id: str
    user_id: str
    state: str
    answer: str | None  # short answer / chosen option
    attachments: list[Attachment] = field(default_factory=list)
    draft_grade: float | None = None
    assigned_grade: float | None = None
    updated: datetime | None = None
    link: str | None = None  # where the teacher opens this submission in Classroom


def _due(raw: dict[str, Any]) -> datetime | None:
    d, t = raw.get("dueDate"), raw.get("dueTime") or {}
    return datetime(d["year"], d["month"], d["day"], t.get("hours", 0), t.get("minutes", 0), tzinfo=UTC) if d else None


def _when(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _work(course_id: str, w: dict[str, Any]) -> CourseWork:
    return CourseWork(w["id"], course_id, w.get("title", ""), w.get("description", ""), w.get("maxPoints"), w.get("state", "PUBLISHED"),
                      _due(w), bool(w.get("associatedWithDeveloper")), w.get("workType", "ASSIGNMENT"), w.get("topicId"), _when(w.get("scheduledTime")))


def _submission(course_id: str, w_id: str, s: dict[str, Any]) -> Submission:
    atts = []
    for a in (s.get("assignmentSubmission") or {}).get("attachments", []):
        if "driveFile" in a:
            atts.append(Attachment("drive", a["driveFile"]["id"], a["driveFile"].get("title", "")))
        elif "link" in a:
            atts.append(Attachment("link", a["link"].get("url", ""), a["link"].get("title", "")))
        else:
            atts.append(Attachment("other", "", ""))
    answer = (s.get("shortAnswerSubmission") or {}).get("answer") or (s.get("multipleChoiceSubmission") or {}).get("answer")
    return Submission(s["id"], course_id, w_id, s.get("userId", ""), s.get("state", ""), answer, atts, s.get("draftGrade"),
                      s.get("assignedGrade"), _when(s.get("updateTime")), s.get("alternateLink"))


class ClassroomClient:
    def __init__(self, http: httpx.AsyncClient, auth: TokenSource, *, base: str = CLASSROOM_API, drive_base: str = DRIVE_API) -> None:
        self._http, self._auth, self._base, self._drive = http, auth, base.rstrip("/"), drive_base.rstrip("/")

    async def _headers(self) -> dict[str, str]:
        """The credentials, or a code that says why there are none: Google refusing the stored token (expired after 7 days in Testing, or the
        teacher revoked access) is UNAUTHENTICATED, which needs a new sign-in; no answer at all is UPSTREAM."""
        try:
            return await self._auth.headers()
        except httpx.HTTPStatusError:
            raise ClassroomError("UNAUTHENTICATED") from None
        except httpx.HTTPError:
            raise ClassroomError("UPSTREAM") from None

    async def _call(self, method: str, url: str, **kw: Any) -> httpx.Response:
        headers = await self._headers()
        try:
            r = await self._http.request(method, url, headers=headers, timeout=30, **kw)
        except httpx.HTTPError:
            raise ClassroomError("UPSTREAM") from None
        if r.status_code >= 400:
            raise ClassroomError(ERRORS.get(r.status_code, "UPSTREAM"))
        return r

    async def _pages(self, url: str, key: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        out, token = [], None
        for _ in range(PAGES):
            r = await self._call("GET", url, params={**(params or {}), **({"pageToken": token} if token else {})})
            out += r.json().get(key, [])
            token = r.json().get("nextPageToken")
            if not token:
                break
        return out

    async def folders(self) -> list[dict[str, Any]]:
        """Drive folders this sign-in can see ({id, name}); with the narrow `drive.file` permission only the ones Cortex made."""
        found = await self._pages(f"{self._drive}/files", "files", {"q": "mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                                                                     "orderBy": "name", "pageSize": 100, "fields": "nextPageToken,files(id,name)"})
        return [{"id": f["id"], "name": f.get("name", "")} for f in found]

    # -- reading: what the AI is shown --------------------------------------------------------------
    async def courses(self) -> list[dict[str, Any]]:
        return await self._pages(f"{self._base}/courses", "courses", {"courseStates": "ACTIVE"})

    async def course_name(self, course_id: str) -> str:
        """The class as the teacher sees it in Classroom: its name, and its section if it has one."""
        c = (await self._call("GET", f"{self._base}/courses/{course_id}")).json()
        return " · ".join(x for x in (c.get("name"), c.get("section")) if x)

    async def coursework(self, course_id: str) -> list[CourseWork]:
        raw = await self._pages(f"{self._base}/courses/{course_id}/courseWork", "courseWork", {"courseWorkStates": "PUBLISHED"})
        return [_work(course_id, w) for w in raw]

    async def submissions(self, course_id: str, coursework_id: str, states: tuple[str, ...] = ("TURNED_IN",)) -> list[Submission]:
        raw = await self._pages(f"{self._base}/courses/{course_id}/courseWork/{coursework_id}/studentSubmissions", "studentSubmissions",
                                {"states": list(states)})
        return [_submission(course_id, coursework_id, s) for s in raw]

    async def submission(self, course_id: str, coursework_id: str, submission_id: str) -> Submission:
        r = await self._call("GET", f"{self._base}/courses/{course_id}/courseWork/{coursework_id}/studentSubmissions/{submission_id}")
        return _submission(course_id, coursework_id, r.json())

    async def student_name(self, course_id: str, user_id: str) -> str:
        r = await self._call("GET", f"{self._base}/courses/{course_id}/students/{user_id}")
        return ((r.json().get("profile") or {}).get("name") or {}).get("fullName", "")

    async def drive_meta(self, file_id: str) -> dict[str, Any]:
        """{mimeType, size (int, 0 if unknown)} of a file a student attached."""
        meta = (await self._call("GET", f"{self._drive}/files/{file_id}", params={"fields": "mimeType,size"})).json()
        return {"mimeType": meta.get("mimeType", ""), "size": int(meta.get("size", 0) or 0)}

    async def drive_text(self, file_id: str, mime: str) -> str:
        """A Google Doc exported as text, or a plain-text file read as it is."""
        if mime in EXPORTABLE:
            return (await self._call("GET", f"{self._drive}/files/{file_id}/export", params={"mimeType": EXPORTABLE[mime]})).text
        return (await self._call("GET", f"{self._drive}/files/{file_id}", params={"alt": "media"})).text

    async def download(self, file_id: str, dest: Path, max_bytes: int) -> None:
        """The file's bytes into `dest`; refuses (TOO_LARGE) as soon as more than `max_bytes` have arrived."""
        got = 0
        async with self._http.stream("GET", f"{self._drive}/files/{file_id}", params={"alt": "media"}, headers=await self._headers(),
                                     timeout=120) as r:
            if r.status_code >= 400:
                raise ClassroomError(ERRORS.get(r.status_code, "UPSTREAM"))
            with dest.open("wb") as out:
                async for chunk in r.aiter_bytes(1 << 20):
                    got += len(chunk)
                    if got > max_bytes:
                        raise ClassroomError("TOO_LARGE")
                    out.write(chunk)

    # -- writing: only code a person's approval has reached --------------------------------------------
    async def create_course(self, name: str) -> dict[str, str]:
        """A new course owned by the signed-in teacher ({id, name, url, state}). The state is NOT asked for in the request: Google answers a create
        with `courseState: ACTIVE` with 403 `@CourseStateDenied` to a teacher who may create courses (a personal Gmail among them). It is created
        provisioned, then moved to ACTIVE if Google lets this account do that; if not, the course is still made and `state` says where it stands."""
        r = await self._call("POST", f"{self._base}/courses", json={"name": name[:750], "ownerId": "me"})
        c = r.json()
        if c.get("courseState", "PROVISIONED") != "ACTIVE":
            try:
                c = (await self._call("PATCH", f"{self._base}/courses/{c['id']}", params={"updateMask": "courseState"}, json={"courseState": "ACTIVE"})).json()
            except ClassroomError as e:
                if e.code != "PERMISSION_DENIED":
                    raise
        return {"id": str(c["id"]), "name": c.get("name", name), "url": c.get("alternateLink", ""), "state": c.get("courseState", "PROVISIONED")}

    async def create_coursework(self, course_id: str, *, title: str, description: str, max_points: int, due: datetime | None,
                                published: bool, materials: list[dict[str, Any]] | None = None, topic_id: str | None = None,
                                scheduled: datetime | None = None, assignees: list[str] | None = None) -> CourseWork:
        """`materials`: [{kind: drive, id, share} | {kind: link, url} | {kind: youtube, id} | {kind: form, url}], attached as the teacher chose them.
        `scheduled`: Classroom itself publishes it then (it is a DRAFT until that time, so `published` is ignored). `assignees`: student ids; none = the whole class."""
        body: dict[str, Any] = {"title": title, "description": description, "maxPoints": max_points, "workType": "ASSIGNMENT",
                                "state": "PUBLISHED" if published and not scheduled else "DRAFT"}
        if materials:
            body["materials"] = [material_body(x) for x in materials]
        if due:
            body |= _due_body(due)
        if topic_id:
            body["topicId"] = topic_id
        if scheduled:
            body["scheduledTime"] = wire(scheduled)
        if assignees:
            body |= {"assigneeMode": "INDIVIDUAL_STUDENTS", "individualStudentsOptions": {"studentIds": assignees}}
        r = await self._call("POST", f"{self._base}/courses/{course_id}/courseWork", json=body)
        return _work(course_id, r.json())

    async def patch_coursework(self, work: CourseWork, **changes: Any) -> CourseWork:
        """Changes what Classroom lets be changed after a piece of work exists: title, description, max_points, due, topic_id, scheduled (a value of
        None clears the due date, the topic or the schedule). Its attachments cannot be changed through the API, only on the Classroom page.
        Only work this app created: Google refuses the rest, so it is refused here before asking."""
        if not work.ours:
            raise ClassroomError("NOT_OURS")
        fields = {"title": "title", "description": "description", "max_points": "maxPoints", "topic_id": "topicId", "scheduled": "scheduledTime"}
        body: dict[str, Any] = {}
        mask: list[str] = []
        for key, value in changes.items():
            if key == "due":
                mask += ["dueDate", "dueTime"]
                body |= _due_body(value) if value else {}
            elif key in fields:
                mask.append(fields[key])
                if value is not None:
                    body[fields[key]] = wire(value) if key == "scheduled" else value
            else:
                raise ClassroomError("INVALID_ARGUMENT")
        if not mask:
            return work
        r = await self._call("PATCH", f"{self._base}/courses/{work.course_id}/courseWork/{work.id}", params={"updateMask": ",".join(mask)}, json=body)
        return _work(work.course_id, r.json())

    async def publish_coursework(self, work: CourseWork) -> CourseWork:
        """A draft made visible to students now. One way only: Classroom does not let published work go back to a draft."""
        if not work.ours:
            raise ClassroomError("NOT_OURS")
        r = await self._call("PATCH", f"{self._base}/courses/{work.course_id}/courseWork/{work.id}", params={"updateMask": "state"},
                             json={"state": "PUBLISHED"})
        return _work(work.course_id, r.json())

    async def delete_coursework(self, work: CourseWork) -> None:
        """Deletes the work in Classroom, with its students' submissions. Only work this app created."""
        if not work.ours:
            raise ClassroomError("NOT_OURS")
        await self._call("DELETE", f"{self._base}/courses/{work.course_id}/courseWork/{work.id}")

    async def get_coursework(self, course_id: str, coursework_id: str) -> CourseWork:
        return _work(course_id, (await self._call("GET", f"{self._base}/courses/{course_id}/courseWork/{coursework_id}")).json())

    async def topics(self, course_id: str) -> list[dict[str, str]]:
        raw = await self._pages(f"{self._base}/courses/{course_id}/topics", "topic")
        return [{"id": str(t["topicId"]), "name": t.get("name", "")} for t in raw]

    async def create_topic(self, course_id: str, name: str) -> dict[str, str]:
        r = await self._call("POST", f"{self._base}/courses/{course_id}/topics", json={"name": name[:100]})
        return {"id": str(r.json()["topicId"]), "name": r.json().get("name", name)}

    async def students(self, course_id: str) -> list[dict[str, str]]:
        """The class list ({id, name}), for giving a piece of work to some of the students."""
        raw = await self._pages(f"{self._base}/courses/{course_id}/students", "students")
        return [{"id": str(x["userId"]), "name": ((x.get("profile") or {}).get("name") or {}).get("fullName", "")} for x in raw]

    async def create_announcement(self, course_id: str, *, text: str, published: bool) -> str:
        """Posts to the course's stream and returns the announcement's id. A DRAFT is seen only by the course's teachers, who publish it
        from Classroom themselves; Google caps the text at 30,000 characters."""
        r = await self._call("POST", f"{self._base}/courses/{course_id}/announcements",
                             json={"text": text[:30_000], "state": "PUBLISHED" if published else "DRAFT"})
        return str(r.json()["id"])

    async def set_grade(self, work: CourseWork, submission_id: str, grade: float, *, assign: bool) -> None:
        """`draftGrade` is what the teacher sees; with `assign` it also becomes the grade the student sees once returned."""
        if not work.ours:
            raise ClassroomError("NOT_OURS")
        fields = ["draftGrade", "assignedGrade"] if assign else ["draftGrade"]
        body = {f: round(grade, 2) for f in fields}
        await self._call("PATCH", f"{self._base}/courses/{work.course_id}/courseWork/{work.id}/studentSubmissions/{submission_id}",
                         params={"updateMask": ",".join(fields)}, json=body)

    async def return_submission(self, work: CourseWork, submission_id: str) -> None:
        if not work.ours:
            raise ClassroomError("NOT_OURS")
        await self._call("POST", f"{self._base}/courses/{work.course_id}/courseWork/{work.id}/studentSubmissions/{submission_id}:return", json={})


def _due_body(due: datetime) -> dict[str, Any]:
    due = due.astimezone(UTC)
    return {"dueDate": {"year": due.year, "month": due.month, "day": due.day}, "dueTime": {"hours": due.hour, "minutes": due.minute}}


def material_body(material: dict[str, Any]) -> dict[str, Any]:
    """One stored attachment as Classroom's `Material`. A Drive file is shared with students as the teacher chose (view, edit, or a copy each);
    a YouTube video and a Google Form are shown by Classroom as such, not as a plain link."""
    kind = material["kind"]
    if kind == "drive":
        return {"driveFile": {"driveFile": {"id": material["id"]}, "shareMode": material.get("share", "VIEW")}}
    if kind == "youtube":
        return {"youtubeVideo": {"id": material["id"]}}
    if kind == "form":
        return {"form": {"formUrl": material["url"]}}
    return {"link": {"url": material["url"]}}


def valid_id(value: str) -> bool:
    """Classroom ids are digits; refused before they are put into a URL."""
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value))


def open_classroom(secret: bytes, *, base: str | None = None, drive_base: str | None = None, http: httpx.AsyncClient | None = None) -> ClassroomClient:
    """The client for a Google account. `secret` is the decrypted {client_id, client_secret, refresh_token}. The HTTP client is made here so that
    no other package imports a network library."""
    import json

    from cortex_leads.connectors.google_auth import RefreshToken

    http = http or httpx.AsyncClient()
    data = json.loads(secret)
    s = get_settings()
    return ClassroomClient(http, RefreshToken(data["client_id"], data["client_secret"], data["refresh_token"], http),
                           base=base or s.CLASSROOM_API_BASE, drive_base=drive_base or s.DRIVE_API_BASE)
