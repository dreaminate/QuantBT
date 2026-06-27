import { type ThemeMode, useThemeMode } from "../lib/theme";

export function ThemeModeControl({
  value,
  onChange,
}: {
  value: ThemeMode;
  onChange: (mode: ThemeMode) => void;
}) {
  const options: { value: ThemeMode; label: string; title: string }[] = [
    { value: "light", label: "明亮", title: "使用明亮模式" },
    { value: "dark", label: "黑暗", title: "使用黑暗模式" },
    { value: "system", label: "系统", title: "跟随系统外观" },
  ];
  return (
    <div className="cc-theme-switcher" role="group" aria-label="主题模式">
      {options.map((item) => (
        <button
          key={item.value}
          type="button"
          className={value === item.value ? "active" : ""}
          onClick={() => onChange(item.value)}
          title={item.title}
          aria-pressed={value === item.value}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export function ConnectedThemeModeControl() {
  const theme = useThemeMode();
  return <ThemeModeControl value={theme.mode} onChange={theme.setMode} />;
}
