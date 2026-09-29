// The tabs of the Settings page (the current one is in the URL: /settings?tab=...).

export const SETTINGS_TABS = [
  { id: "library", label: "Library" },
  { id: "import", label: "Import" },
  { id: "external", label: "External services" },
  { id: "album-search", label: "Album search" },
  { id: "transcripts", label: "Transcripts" },
  { id: "users", label: "Users" },
] as const;

export type SettingsTab = (typeof SETTINGS_TABS)[number]["id"];

/** Link to a tab of the Settings page. */
export const settingsUrl = (tab: SettingsTab) => `/settings?tab=${tab}`;
