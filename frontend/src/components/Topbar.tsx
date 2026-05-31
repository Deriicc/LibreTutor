import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

function parseCourseId(path: string): string | null {
  const m = path.match(/^\/courses\/([^/]+)/);
  return m ? m[1] : null;
}

export function Topbar() {
  const location = useLocation();
  const navigate = useNavigate();
  const courseId = parseCourseId(location.pathname);
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="topbar">
      <Link to="/" className="topbar-brand">
        <div className="mark">Σ</div>
        <span>Σωκράτης</span>
      </Link>

      <div
        className="topbar-divider"
        style={{ width: 1, height: 22, background: "var(--paper-4)" }}
      />

      {courseId && (
        <nav className="topbar-crumbs">
          <Link to={`/courses/${courseId}`} className="crumb">
            章节树
          </Link>
          <span className="sep">/</span>
          <span className="crumb crumb-current">
            {location.pathname.includes("/diary")
              ? "教师手记"
              : location.pathname.includes("/teacher-config")
                ? "角色卡"
                : location.pathname.includes("/exercise")
                  ? "作业"
                  : location.pathname.includes("/kp/")
                    ? "对话"
                    : "课程"}
          </span>
        </nav>
      )}

      <div className="topbar-spacer" />

      {/* Desktop nav links */}
      {courseId && (
        <div className="topbar-course-actions">
          <button
            type="button"
            className="btn btn-quiet btn-sm"
            onClick={() => navigate(`/courses/${courseId}/teacher-config`)}
          >
            角色卡
          </button>
          <button
            type="button"
            className="btn btn-quiet btn-sm"
            onClick={() => navigate(`/courses/${courseId}/diary`)}
          >
            教师手记
          </button>
        </div>
      )}

      <div className="topbar-user">
        <button
          type="button"
          className="btn btn-quiet btn-sm"
          onClick={() => navigate("/settings")}
        >
          设置
        </button>
      </div>

      {/* Mobile hamburger */}
      <button
        type="button"
        className="topbar-hamburger"
        onClick={() => setMenuOpen(!menuOpen)}
        aria-label="菜单"
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          {menuOpen ? (
            <path d="M5 5L15 15M15 5L5 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          ) : (
            <>
              <path d="M3 6H17" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M3 10H17" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M3 14H17" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </>
          )}
        </svg>
      </button>

      {/* Mobile menu overlay */}
      {menuOpen && (
        <div className="topbar-mobile-menu" onClick={() => setMenuOpen(false)}>
          <div className="topbar-mobile-menu-inner" onClick={(e) => e.stopPropagation()}>
            {courseId && (
              <>
                <button
                  type="button"
                  className="topbar-mobile-link"
                  onClick={() => { navigate(`/courses/${courseId}/teacher-config`); setMenuOpen(false); }}
                >
                  角色卡
                </button>
                <button
                  type="button"
                  className="topbar-mobile-link"
                  onClick={() => { navigate(`/courses/${courseId}/diary`); setMenuOpen(false); }}
                >
                  教师手记
                </button>
                <div className="topbar-mobile-divider" />
              </>
            )}
            <button
              type="button"
              className="topbar-mobile-link"
              onClick={() => { navigate("/settings"); setMenuOpen(false); }}
            >
              设置
            </button>
          </div>
        </div>
      )}
    </header>
  );
}
