import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import { useSession } from './api/hooks'
import { can, homeOf } from './components/can'
import { Shell } from './components/Shell'
import { ErrorBox, Loading } from './components/ui'
import { AssignmentPage } from './pages/AssignmentPage'
import { Audit } from './pages/Audit'
import { Account } from './pages/Account'
import { Assistant } from './pages/Assistant'
import { Data } from './pages/Data'
import { Settings } from './pages/Settings'
import { GradingLink } from './pages/Grading'
import { Inbox } from './pages/Inbox'
import { ClassPage, LessonLink } from './pages/ClassPage'
import { Lessons } from './pages/Lessons'
import { Forgot, ResetPassword } from './pages/Recovery'
import { Login } from './pages/Login'
import { SandboxDetail } from './pages/SandboxDetail'
import { SkillForm } from './pages/SkillForm'
import { SkillDetail } from './pages/SkillDetail'
import { Skills } from './pages/Skills'
import { SourceNew } from './pages/SourceNew'
import { Team } from './pages/Team'
import { Templates } from './pages/Templates'
import { Tools } from './pages/Tools'
import { Perm } from './api/enums'
import { AdminApp } from './admin/AdminApp'

/** A page the person's role does not have goes back to where they start instead of showing a wall of refusals. */
function Needs({ perm, children }: { perm: Perm; children: ReactNode }) {
  const { data: me } = useSession()
  return can(me, perm) ? <>{children}</> : <Navigate to={homeOf(me)} replace />
}

function Home() {
  const { data: me } = useSession()
  return <Navigate to={homeOf(me)} replace />
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
  return <Shell me={me} />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/forgot" element={<Forgot />} />
      <Route path="/reset" element={<ResetPassword />} />
      <Route path="/admin/*" element={<AdminApp />} />  {/* the platform admin page (WP47): its own sign-in, never the console's session */}
      <Route element={<Authed />}>
        <Route path="/" element={<Home />} />
        <Route path="/inbox/:id?" element={<Needs perm={Perm.INBOX_USE}><Inbox /></Needs>} />
        <Route path="/classes" element={<Needs perm={Perm.LESSONS_READ}><Lessons /></Needs>} />
        <Route path="/classes/:classId" element={<Needs perm={Perm.LESSONS_READ}><ClassPage /></Needs>} />
        <Route path="/classes/:classId/assignments/:assignmentId" element={<Needs perm={Perm.GRADING_USE}><AssignmentPage /></Needs>} />
        {/* the links in team messages, and the old menu entries, keep working */}
        <Route path="/lessons" element={<Navigate to="/classes" replace />} />
        <Route path="/lessons/classes/:classId" element={<RedirectClass />} />
        <Route path="/lessons/:id" element={<Needs perm={Perm.LESSONS_READ}><LessonLink /></Needs>} />
        <Route path="/grading/:id?" element={<Needs perm={Perm.GRADING_USE}><GradingLink /></Needs>} />
        <Route path="/assignments" element={<Navigate to="/classes" replace />} />
        <Route path="/templates" element={<Needs perm={Perm.GRADING_USE}><Templates /></Needs>} />
        <Route path="/skills" element={<Needs perm={Perm.SKILLS_READ}><Skills /></Needs>} />
        <Route path="/skills/new" element={<Needs perm={Perm.SKILLS_READ}><SkillForm /></Needs>} />
        <Route path="/skills/:id" element={<Needs perm={Perm.SKILLS_READ}><SkillDetail /></Needs>} />
        <Route path="/skills/:id/edit" element={<Needs perm={Perm.SKILLS_READ}><SkillForm /></Needs>} />
        {/* a sandbox is not something to manage: the jobs live in Cài đặt → AI, and every job exists from the first day */}
        <Route path="/sandboxes" element={<Navigate to="/settings?tab=ai" replace />} />
        <Route path="/sandboxes/:id" element={<Needs perm={Perm.SANDBOXES_MANAGE}><SandboxDetail /></Needs>} />
        <Route path="/tools" element={<Needs perm={Perm.TOOLS_MANAGE}><Tools /></Needs>} />
        <Route path="/tools/sources/new" element={<Needs perm={Perm.SOURCES_MANAGE}><SourceNew /></Needs>} />
        <Route path="/settings" element={<Needs perm={Perm.SETTINGS_MANAGE}><Settings /></Needs>} />
        <Route path="/data" element={<Needs perm={Perm.CATALOG_READ}><Data /></Needs>} />
        <Route path="/start" element={<Home />} />  {/* the old Bắt đầu page: gone; its address still leads somewhere */}
        <Route path="/google" element={<Navigate to="/settings" replace />} />
        <Route path="/assistant" element={<Needs perm={Perm.ASSISTANT_USE}><Assistant /></Needs>} />
        <Route path="/audit" element={<Audit />} />
        <Route path="/account" element={<Account />} />
        <Route path="/team" element={<Needs perm={Perm.TEAM_MANAGE}><Team /></Needs>} />
        <Route path="*" element={<Navigate to="/inbox" replace />} />
      </Route>
    </Routes>
  )
}
