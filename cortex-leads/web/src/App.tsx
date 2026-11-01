import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import { useSession } from './api/hooks'
import { can } from './components/can'
import { Shell } from './components/Shell'
import { ErrorBox, Loading } from './components/ui'
import { AssignmentPage } from './pages/AssignmentPage'
import { Audit } from './pages/Audit'
import { Account, ForcedPassword } from './pages/Account'
import { Assistant } from './pages/Assistant'
import { Settings } from './pages/Settings'
import { GradingLink } from './pages/Grading'
import { Inbox } from './pages/Inbox'
import { ClassPage, LessonLink } from './pages/ClassPage'
import { Lessons } from './pages/Lessons'
import { Login } from './pages/Login'
import { SandboxDetail } from './pages/SandboxDetail'
import { Sandboxes } from './pages/Sandboxes'
import { SkillForm } from './pages/SkillForm'
import { SkillDetail } from './pages/SkillDetail'
import { Skills } from './pages/Skills'
import { SourceNew } from './pages/SourceNew'
import { Team } from './pages/Team'
import { Tools } from './pages/Tools'

/** A page the person's role does not have goes back to the inbox instead of showing a wall of refusals. */
function Needs({ perm, children }: { perm: string; children: ReactNode }) {
  const { data: me } = useSession()
  return can(me, perm) ? <>{children}</> : <Navigate to="/inbox" replace />
}

function RedirectClass() {
  const { classId = '' } = useParams()
  return <Navigate to={`/classes/${classId}`} replace />
}

function Authed() {
  const { data: me, isPending, isError, refetch } = useSession()
  if (isPending) return <Loading />
  if (isError) return <ErrorBox onRetry={() => refetch()}>Không kết nối được máy chủ.</ErrorBox>
  if (!me) return <Navigate to="/login" replace />
  if (me.must_change_password) return <ForcedPassword />  // a temporary password gets the person nothing but this
  return <Shell me={me} />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Authed />}>
        <Route path="/" element={<Navigate to="/inbox" replace />} />
        <Route path="/inbox/:id?" element={<Inbox />} />
        <Route path="/classes" element={<Needs perm="lessons.read"><Lessons /></Needs>} />
        <Route path="/classes/:classId" element={<Needs perm="lessons.read"><ClassPage /></Needs>} />
        <Route path="/classes/:classId/assignments/:assignmentId" element={<Needs perm="grading.use"><AssignmentPage /></Needs>} />
        {/* the links in team messages, and the old menu entries, keep working */}
        <Route path="/lessons" element={<Navigate to="/classes" replace />} />
        <Route path="/lessons/classes/:classId" element={<RedirectClass />} />
        <Route path="/lessons/:id" element={<Needs perm="lessons.read"><LessonLink /></Needs>} />
        <Route path="/grading/:id?" element={<Needs perm="grading.use"><GradingLink /></Needs>} />
        <Route path="/assignments" element={<Navigate to="/classes" replace />} />
        <Route path="/skills" element={<Skills />} />
        <Route path="/skills/new" element={<SkillForm />} />
        <Route path="/skills/:id" element={<SkillDetail />} />
        <Route path="/skills/:id/edit" element={<SkillForm />} />
        <Route path="/sandboxes" element={<Sandboxes />} />
        <Route path="/sandboxes/:id" element={<Needs perm="sandboxes.manage"><SandboxDetail /></Needs>} />
        <Route path="/tools" element={<Needs perm="tools.manage"><Tools /></Needs>} />
        <Route path="/tools/sources/new" element={<Needs perm="sources.manage"><SourceNew /></Needs>} />
        <Route path="/settings" element={<Needs perm="sources.manage"><Settings /></Needs>} />
        <Route path="/google" element={<Navigate to="/settings" replace />} />
        <Route path="/assistant" element={<Needs perm="assistant.use"><Assistant /></Needs>} />
        <Route path="/audit" element={<Audit />} />
        <Route path="/account" element={<Account />} />
        <Route path="/team" element={<Needs perm="team.manage"><Team /></Needs>} />
        <Route path="*" element={<Navigate to="/inbox" replace />} />
      </Route>
    </Routes>
  )
}
