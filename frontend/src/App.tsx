import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Topbar } from "./components/Topbar";

const CoursePage = lazy(() => import("./routes/CoursePage").then(m => ({ default: m.CoursePage })));
const CreateCoursePage = lazy(() => import("./routes/CreateCoursePage").then(m => ({ default: m.CreateCoursePage })));
const ExercisePage = lazy(() => import("./routes/ExercisePage").then(m => ({ default: m.ExercisePage })));
const HomePage = lazy(() => import("./routes/HomePage").then(m => ({ default: m.HomePage })));
const KPPage = lazy(() => import("./routes/KPPage").then(m => ({ default: m.KPPage })));
const AssessmentPage = lazy(() => import("./routes/AssessmentPage").then(m => ({ default: m.AssessmentPage })));
const DiaryBook = lazy(() => import("./routes/DiaryBook").then(m => ({ default: m.DiaryBook })));
const TeacherConfigPage = lazy(() => import("./routes/TeacherConfigPage").then(m => ({ default: m.TeacherConfigPage })));
const SettingsPage = lazy(() => import("./routes/SettingsPage").then(m => ({ default: m.SettingsPage })));

function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-root">
      <Topbar />
      {children}
    </div>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={null}>
        <Routes>
          <Route path="/" element={<AppShell><HomePage /></AppShell>} />
          <Route path="/courses/new" element={<AppShell><CreateCoursePage /></AppShell>} />
          <Route path="/courses/:courseId" element={<AppShell><CoursePage /></AppShell>} />
          <Route path="/courses/:courseId/kp/:kpId" element={<AppShell><KPPage /></AppShell>} />
          <Route path="/courses/:courseId/kp/:kpId/exercise" element={<AppShell><ExercisePage /></AppShell>} />
          <Route path="/courses/:courseId/kp/:kpId/assessment" element={<AppShell><AssessmentPage /></AppShell>} />
          <Route path="/courses/:courseId/diary" element={<AppShell><DiaryBook /></AppShell>} />
          <Route path="/courses/:courseId/teacher-config" element={<AppShell><TeacherConfigPage /></AppShell>} />
          <Route path="/settings" element={<AppShell><SettingsPage /></AppShell>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
