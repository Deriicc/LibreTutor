import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { getSettings } from "../api/settings";
import { EN } from "./translations";

export type Lang = "zh" | "en";

type Vars = Record<string, string | number>;

type LanguageContextValue = {
  lang: Lang;
  setLang: (l: Lang) => void;
  /** Translate a Chinese source string. zh → identity; en → EN[key] ?? key.
   * `vars` fills `{name}`-style placeholders in the resolved string. */
  t: (zh: string, vars?: Vars) => string;
};

const STORAGE_KEY = "libretutor.lang";

function readStored(): Lang {
  const v = typeof localStorage !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
  return v === "en" ? "en" : "zh";
}

const LanguageContext = createContext<LanguageContextValue>({
  lang: "zh",
  setLang: () => {},
  t: (zh) => zh,
});

export function LanguageProvider({ children }: { children: ReactNode }) {
  // Init synchronously from localStorage to avoid a flash, then reconcile
  // with the server-stored preference.
  const [lang, setLangState] = useState<Lang>(readStored);

  useEffect(() => {
    document.documentElement.lang = lang === "en" ? "en" : "zh";
  }, [lang]);

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((s) => {
        const server = s.language === "en" ? "en" : "zh";
        if (!cancelled) {
          setLangState(server);
          try {
            localStorage.setItem(STORAGE_KEY, server);
          } catch {
            // ignore
          }
        }
      })
      .catch(() => {
        // offline / not configured — keep the localStorage value
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      // ignore
    }
  }, []);

  const t = useCallback(
    (zh: string, vars?: Vars) => {
      let s = lang === "en" ? EN[zh] ?? zh : zh;
      if (vars) {
        for (const k of Object.keys(vars)) {
          s = s.split(`{${k}}`).join(String(vars[k]));
        }
      }
      return s;
    },
    [lang],
  );

  const value = useMemo(
    () => ({ lang, setLang, t }),
    [lang, setLang, t],
  );

  return (
    <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
  );
}

export function useLanguage(): LanguageContextValue {
  return useContext(LanguageContext);
}
