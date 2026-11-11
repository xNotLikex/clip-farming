# Anti-AI-UI Design Guidelines & Hard Banned Patterns

> Konsolidierter Regelsatz basierend auf den führenden Open-Source-Audits:
> - `JCarterJohnson/vibecoded-design-tells` (devibe_scan)
> - `funboy322/avoid-ai-design`
> - `LeoStehlik/no-slop-ui`
> - `miqdadbadjuber/anti-slop`
> - `Vanszs/Anti-AI-UI`
> - `dev-lou/PixelPilot`

---

## ⛔ Absolute Hard-Bans (Sofortige Disqualifikation als "AI Slop")

1. **Keine Emojis als UI-Icons:**
   - ❌ Emojis wie `🚀`, `✨`, `⚡`, `🎯`, `🎬`, `⚙️`, `🧠`, `📌`, `💬` in Buttons, Badges, Tabs oder Headings.
   - ✅ **Stattdessen:** Präzise, einheitliche monochrome Vektor-Icons (Inline SVG nach Vorbild von Lucide / Heroicons).

2. **Keine Gradient-Texte & Regenbogen-Gradients:**
   - ❌ `bg-clip-text text-transparent`, `-webkit-background-clip: text`.
   - ❌ Generische Lila-zu-Blau/Pink-Verläufe (`from-purple-* to-blue-*`, `#6366f1`, `#a855f7`).
   - ✅ **Stattdessen:** Solide Schriftfarben mit geprüften WCAG 2.2 AA Kontrasten (z. B. `text-slate-100` / `text-white`, `text-slate-400` für Sekundärtexte).

3. **Keine übertriebenen Border-Radien & Pillen-Inflation:**
   - ❌ `rounded-2xl`, `rounded-3xl`, `rounded-full` auf Karten, Modals, Formularen und Panels.
   - ❌ Pill-Buttons überall (`border-radius: 9999px`).
   - ✅ **Stattdessen:** Ein disziplinierter Radius-Maßstab:
     - Container, Cards & Modals: `rounded-lg` (8px)
     - Buttons, Inputs & Selects: `rounded-md` (6px) oder `rounded-lg` (8px)
     - Nur echte Status-Indikator-Punkte oder Avatare nutzen `rounded-full`.

4. **Kein diffuses Neon-Glow & keine schwebenden Glassmorphism-Wände:**
   - ❌ `backdrop-blur-*` mit transluzenten `border-white/10` Rändern auf jedem Panel.
   - ❌ `shadow-[0_0_40px_...]`, bunte Leuchtschatten auf Buttons und Cards.
   - ✅ **Stattdessen:** Feste, solide Oberflächen mit dezenten, 1px-Borders (`border border-slate-800` / `border-zinc-800`) und flacher, funktionaler Schattenhierarchie (`shadow-sm` oder `shadow-md`).

5. **Keine unbegründeten Bouncy-Animationen:**
   - ❌ `hover:scale-105`, `hover:scale-110`, wackelnde Elemente beim Drüberfahren.
   - ✅ **Stattdessen:** Ruhige Farb-/Opazitäts-Transitions (`transition-colors duration-150`, `hover:bg-slate-800`).

---

## 📐 Das Design-Vorbild: Linear / Raycast / GitHub

- **Datendichte (Data Density):** Kompakte, informative Tabellen und Karten statt leerer, aufgeblasener Dribbble-Cards.
- **Farbpalette:** 
  - Neutral-Dark Base: `#090d16` / `#0f172a` (Slate-950 / Slate-900).
  - Borders: `#1e293b` (Slate-800) – präzise 1px Trennlinien.
  - Akzente gezielt und funktional: Amber/Gold `#f59e0b` für Primäraktionen, Emerald `#10b981` für Erfolgs-/Aktivitätsstatus, Rose `#f43f5e` für Destruktivaktionen.
- **Barrierefreiheit (WCAG 2.2):** Alle Texte und Kontrollleisten haben mindestens 4.5:1 Kontrastverhältnis. Formulare besitzen stets eindeutige Labels und funktionale `:focus-visible` Ringe.
