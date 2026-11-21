import React, { createContext, useCallback, useContext, useState } from 'react';
import {
  detectInitialLanguage,
  LANGUAGE_STORAGE_KEY,
  translations,
  type Language,
  type TranslationSchema,
} from './translations';

interface I18nContextValue {
  lang: Language;
  setLang: (next: Language) => void;
  toggleLang: () => void;
  t: TranslationSchema;
}

const I18nContext = createContext<I18nContextValue>({
  lang: 'es',
  setLang: () => {},
  toggleLang: () => {},
  t: translations.es,
});

export const I18nProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [lang, setLangState] = useState<Language>(() => detectInitialLanguage());

  const setLang = useCallback((next: Language) => {
    setLangState(next);
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
    } catch {
      // Ignore storage errors
    }
  }, []);

  const toggleLang = useCallback(() => {
    setLangState((prev) => {
      const next: Language = prev === 'es' ? 'en' : 'es';
      try {
        window.localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
      } catch {
        // Ignore storage errors
      }
      return next;
    });
  }, []);

  return (
    <I18nContext.Provider value={{ lang, setLang, toggleLang, t: translations[lang] }}>
      {children}
    </I18nContext.Provider>
  );
};

export function useI18n(): I18nContextValue {
  return useContext(I18nContext);
}
