# SPEC_PV_TERMINAL.md — Rediseño de frontend PIVOT

**Codename del proyecto:** PV-Terminal (Pivot Visual Terminal)
**Repo objetivo:** `frontend/` dentro de github.com/ogro188/pivot
**Para ejecutar con:** un agente de código autónomo en opencode
**Tipo de tarea:** SOLO capa de presentación. Cero cambios de lógica de negocio.

---

## 0. Contexto para el agente

PIVOT es un sistema de trading algorítmico (Python backend + FastAPI + WebSocket, React/TypeScript frontend) que detecta patrones de estructura de mercado (sweeps de liquidez, order blocks, FVG, MSS) en múltiples timeframes. El frontend actual funciona correctamente a nivel de datos (fetching, WebSocket, estado con Zustand) pero visualmente es un dashboard genérico de Tailwind sin identidad — fondo `bg-gray-900`, azul `blue-600` por defecto, sin tipografía propia, sin tokens de diseño.

**Objetivo de esta tarea:** darle al frontend una identidad visual de terminal profesional densa (referencia: Bloomberg Terminal, TradingView), coherente con el nombre del propio sistema ("RADAR v2.0", filosofía "radar puro"), sin tocar ni una línea de lógica de datos, fetching, WebSocket, ni el store de Zustand.

**Restricción no negociable:** este es un cambio de presentación (CSS, Tailwind, estructura JSX, componentes visuales nuevos). Ninguna función en `api.ts`, ningún hook de `store.ts`, ninguna llamada a `useQuery`/`useEffect` que traiga datos puede modificarse en su comportamiento. Si un componente necesita reestructurar su JSX para el nuevo layout, los datos que consume y las funciones que llama deben quedar exactamente iguales.

---

## 1. Sistema de diseño (tokens ya validados — compilan sin error)

### 1.1 Paleta de color

| Token | Hex | Uso |
|---|---|---|
| `base-bg` | `#0B0E14` | Fondo general de la app |
| `base-panel` | `#141922` | Paneles, cards, navbar |
| `base-panel2` | `#191F2A` | Paneles anidados/hover |
| `base-line` | `#232936` | Bordes, divisores, grillas — siempre 1px, nunca sombras |
| `text-primary` | `#E4E7EC` | Texto principal (no blanco puro) |
| `text-secondary` | `#7A8699` | Labels, texto secundario |
| `text-muted` | `#4B5563` | Texto deshabilitado/placeholder |
| `signal-long` | `#2FBF71` | **Exclusivo** para dirección alcista/compra. Nunca decorativo. |
| `signal-short` | `#D64550` | **Exclusivo** para dirección bajista/venta. Nunca decorativo. |
| `brand-cyan` | `#37E0C4` | Color de marca de PIVOT — estados activos, foco, el indicador de radar. Nunca usado para dirección de mercado (esa semántica es solo de `signal-long`/`signal-short`). |

**Regla dura:** `signal-long`/`signal-short` no se usan para nada que no sea dirección de mercado real (LONG/SHORT de una señal u operación). Si hace falta un color de "éxito" genérico de UI (ej. "guardado correctamente"), usar `brand-cyan`, no `signal-long` — mezclar esa semántica confunde visualmente "el sistema funcionó" con "el mercado subió".

### 1.2 Tipografía

Familia IBM Plex completa (Google Fonts, ya cargada vía `<link>` en `index.html`):
- **`font-mono`** (IBM Plex Mono): todo número — precios, cifras, timestamps, IDs. Usar junto con la clase utilitaria `.tabular` para alineación de columnas.
- **`font-sans`** (IBM Plex Sans): labels, texto de UI, botones, navegación.
- **`font-condensed`** (IBM Plex Sans Condensed): chips, badges, tags de sesión/detector — donde el espacio horizontal es limitado. Uso típico: `text-[11px] tracking-widest uppercase`.

### 1.3 Archivos de tokens (ya escritos y probados — NO modificar sin razón, son la base de todo lo demás)

`frontend/tailwind.config.js`:
```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        base: { bg: '#0B0E14', panel: '#141922', panel2: '#191F2A', line: '#232936' },
        text: { primary: '#E4E7EC', secondary: '#7A8699', muted: '#4B5563' },
        signal: { long: '#2FBF71', short: '#D64550' },
        brand: { cyan: '#37E0C4' },
      },
      fontFamily: {
        mono: ['"IBM Plex Mono"', 'monospace'],
        sans: ['"IBM Plex Sans"', 'sans-serif'],
        condensed: ['"IBM Plex Sans Condensed"', 'sans-serif'],
      },
      keyframes: {
        'radar-sweep': { '0%': { transform: 'rotate(0deg)' }, '100%': { transform: 'rotate(360deg)' } },
        'pulse-dot': { '0%, 100%': { opacity: '1' }, '50%': { opacity: '0.3' } },
      },
      animation: {
        'radar-sweep': 'radar-sweep 3s linear infinite',
        'pulse-dot': 'pulse-dot 2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
```

`frontend/index.html` — agregar dentro de `<head>`, antes del cierre:
```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link
  href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Sans+Condensed:wght@500;600;700&display=swap"
  rel="stylesheet"
/>
```

`frontend/src/index.css` (reemplazar contenido completo):
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  body {
    @apply bg-base-bg text-text-primary font-sans antialiased;
    font-feature-settings: "tnum" 1, "lnum" 1;
  }
  ::selection { background-color: rgba(55, 224, 196, 0.3); }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-track { @apply bg-base-panel; }
  ::-webkit-scrollbar-thumb { @apply bg-base-line; }
  ::-webkit-scrollbar-thumb:hover { @apply bg-text-muted; }
  :focus-visible { outline: 2px solid #37E0C4; outline-offset: 1px; }
}

@layer components {
  .tabular { font-variant-numeric: tabular-nums; @apply font-mono; }
  .panel { @apply bg-base-panel border border-base-line; }
  .hairline-b { @apply border-b border-base-line; }
  .hairline-t { @apply border-t border-base-line; }
}
```

**Verificación obligatoria tras aplicar estos 3 archivos:** correr `npm run build` dentro de `frontend/` y confirmar que termina sin error antes de tocar ningún componente. Si falla acá, no seguir — algo del entorno no matchea lo documentado.

---

## 2. Layout general de la aplicación (wireframe)

```
┌─ NAVBAR: logo + radar-sweep + tabs + estado WS ──────────────────────────┐
├──────────┬──────────────────────────────────────────┬────────────────────┤
│          │                                            │                    │
│  RAIL    │              CHART (dominante)             │  DETECTOR READOUT  │
│  activos │                                            │  D0..D5 hex chips  │
│ (angosto)│──────────────────────────────────────────  ├────────────────────┤
│          │        SIGNAL FEED (filas compactas)       │  SESSION / RELOJ    │
├──────────┴──────────────────────────────────────────┴────────────────────┤
│ CONSOLA / LOG TAPE (monoespaciada, scroll, tipo cinta de teletipo)          │
└─────────────────────────────────────────────────────────────────────────┘
```

Densidad objetivo: sin padding "de card de SaaS" (nada de `p-6 rounded-xl shadow-lg`). Usar `p-2` a `p-3` como máximo, bordes de 1px (`border-base-line`), `border-radius: 0` o como mucho `rounded-sm` — la estética es de instrumento, no de app de consumo.

---

## 3. Componentes de referencia (ya construidos, código completo — usar como patrón exacto para el resto)

### 3.1 `frontend/src/components/NavBar.tsx` (reemplazar completo)

```tsx
import { Link, useLocation } from 'react-router-dom'
import { useStore } from '../store'

const links = [
  { to: '/', label: 'HUB' },
  { to: '/backtest', label: 'BACKTEST' },
  { to: '/estrategias', label: 'ESTRATEGIAS' },
  { to: '/config', label: 'CONFIG' },
]

function RadarSweep({ active }: { active: boolean }) {
  return (
    <div className="relative w-3.5 h-3.5 shrink-0">
      <div className="absolute inset-0 rounded-full border border-base-line" />
      {active && (
        <div
          className="absolute inset-0 rounded-full animate-radar-sweep"
          style={{ background: 'conic-gradient(from 0deg, transparent 0%, transparent 75%, rgba(55,224,196,0.9) 100%)' }}
        />
      )}
      <div className={`absolute inset-[3px] rounded-full ${active ? 'bg-brand-cyan/20' : 'bg-transparent'}`} />
    </div>
  )
}

export default function NavBar() {
  const loc = useLocation()
  const wsConnected = useStore((s) => s.wsConnected)
  const soundsEnabled = useStore((s) => s.soundsEnabled)
  const setSoundsEnabled = useStore((s) => s.setSoundsEnabled)

  return (
    <nav className="bg-base-panel hairline-b px-3 h-11 flex items-center gap-1 font-condensed text-[13px] tracking-wide uppercase">
      <div className="flex items-center gap-2 pr-3 mr-2 border-r border-base-line h-full">
        <RadarSweep active={wsConnected} />
        <span className="font-mono font-semibold text-text-primary tracking-tight normal-case text-sm">PIVOT</span>
      </div>
      {links.map((l) => (
        <Link
          key={l.to}
          to={l.to}
          className={`px-3 h-full flex items-center border-b-2 transition-colors ${
            loc.pathname === l.to
              ? 'border-brand-cyan text-text-primary'
              : 'border-transparent text-text-secondary hover:text-text-primary hover:border-base-line'
          }`}
        >
          {l.label}
        </Link>
      ))}
      <div className="ml-auto flex items-center gap-3">
        <button
          onClick={() => setSoundsEnabled(!soundsEnabled)}
          className={`w-7 h-7 flex items-center justify-center border transition-colors ${
            soundsEnabled ? 'border-brand-cyan/50 text-brand-cyan' : 'border-base-line text-text-muted hover:text-text-secondary'
          }`}
          title={soundsEnabled ? 'Desactivar sonidos' : 'Activar sonidos'}
        >
          {soundsEnabled ? '♪' : '✕'}
        </button>
        <div className="flex items-center gap-1.5 pl-3 border-l border-base-line h-full">
          <div className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-signal-long animate-pulse-dot' : 'bg-signal-short'}`} />
          <span className="font-mono text-[11px] text-text-secondary normal-case">{wsConnected ? 'LIVE' : 'OFFLINE'}</span>
        </div>
      </div>
    </nav>
  )
}
```

Nota de por qué está hecho así: el radar-sweep no es decoración — es el heartbeat visual del estado de WebSocket (`wsConnected`), reemplazando el punto de color plano que había antes. Es el único elemento con movimiento de toda la interfaz; todo lo demás queda quieto y disciplinado a propósito.

### 3.2 `frontend/src/components/DetectorReadout.tsx` (componente nuevo, crear archivo)

```tsx
interface DetectorReadoutProps {
  activos: string[]
  clasificacion?: Record<string, 'A' | 'B' | 'C'>
}

const DETECTORES = ['D0', 'D1', 'D2', 'D3', 'D4', 'D5'] as const

const NOMBRES: Record<string, string> = {
  D0: 'ESTRUCTURA', D1: 'TENDENCIA', D2: 'SWEEP', D3: 'FVG', D4: 'ORDER BLOCK', D5: 'MSS',
}

export default function DetectorReadout({ activos, clasificacion = {} }: DetectorReadoutProps) {
  return (
    <div className="panel p-2.5 space-y-1.5">
      <div className="font-condensed text-[11px] tracking-widest text-text-muted uppercase mb-2">Detectores</div>
      {DETECTORES.map((d) => {
        const activo = activos.includes(d)
        const clase = clasificacion[d]
        return (
          <div key={d} className="flex items-center gap-2">
            <svg width="12" height="12" viewBox="0 0 12 12" className="shrink-0">
              <polygon points="6,0 12,6 6,12 0,6" fill={activo ? '#37E0C4' : 'none'} stroke={activo ? '#37E0C4' : '#232936'} strokeWidth="1" />
            </svg>
            <span className={`font-mono text-[11px] ${activo ? 'text-text-primary' : 'text-text-muted'}`}>{d}</span>
            <span className={`font-condensed text-[11px] ${activo ? 'text-text-secondary' : 'text-text-muted/50'}`}>{NOMBRES[d]}</span>
            {clase && activo && (
              <span className="ml-auto font-mono text-[10px] px-1 border border-base-line text-text-secondary">{clase}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}
```

**Dónde usarlo:** en `ActivoPage.tsx`, en el rail derecho, alimentado por los detectores activos de la señal más reciente del activo actual (ya vienen en el objeto `signal` que devuelve `fetchSignals` — el agente debe revisar `SignalCard.tsx` para ver el shape exacto del campo de detectores antes de conectar los datos, sin inventar un campo que no exista en la respuesta real de la API).

---

## 4. Tabla de migración sistemática (aplicar a TODOS los archivos restantes)

Buscar y reemplazar estos patrones en `App.tsx`, `pages/*.tsx`, `components/ChartHost.tsx`, `components/SignalCard.tsx`, `components/ParamForm.tsx`, `components/SignalCountdown.tsx`:

| Patrón viejo | Reemplazo |
|---|---|
| `bg-gray-900` | `bg-base-bg` |
| `bg-gray-800` | `bg-base-panel` |
| `bg-gray-700` | `bg-base-panel2` o `bg-base-line` según sea fondo o borde |
| `border-gray-700` / `border-gray-600` | `border-base-line` |
| `text-gray-100` / `text-white` (texto de contenido, no íconos) | `text-text-primary` |
| `text-gray-300` / `text-gray-400` | `text-text-secondary` |
| `text-gray-500` | `text-text-muted` |
| `bg-blue-600` (para navegación/estado activo genérico) | `bg-brand-cyan/20 border border-brand-cyan text-brand-cyan` (nunca fondo cian sólido grande — es un acento, no un color de superficie) |
| `bg-green-600` / `text-green-400` (cuando es semánticamente compra/alcista) | `signal-long` |
| `bg-red-600` / `text-red-400` (cuando es semánticamente venta/bajista) | `signal-short` |
| `rounded-lg`, `rounded-xl` | `rounded-sm` o sin redondeo — la estética es de instrumento, no de card de consumo |
| Cualquier número/precio/timestamp en JSX | agregar clase `.tabular font-mono` si no la tiene |
| `font-bold` en headers de sección | reemplazar por `font-condensed text-[11px] tracking-widest uppercase text-text-muted` para labels de sección (no todo título necesita ser grande y en negrita — en un terminal denso, los labels son chicos y las cifras son las que llevan el peso visual) |

**Antes de aplicar la tabla a cada archivo:** leer el componente completo primero. La tabla es una guía de tokens, no un sed automático ciego — hay lugares donde `green`/`red` es decorativo de UI (ej. un ícono de "conectado") y no señal de mercado; ahí no corresponde `signal-long`/`signal-short`, corresponde `brand-cyan` o un verde/rojo neutro de estado del sistema. Usar criterio, no reemplazo mecánico.

---

## 5. Orden de ejecución para el agente

1. Aplicar §1.3 (tokens: `tailwind.config.js`, `index.html`, `index.css`). Correr `npm run build`. Si falla, detenerse y reportar el error exacto — no continuar a ciegas.
2. Reemplazar `NavBar.tsx` con el código de §3.1 tal cual. Correr `npm run dev` y confirmar visualmente (o al menos que compila) antes de seguir.
3. Crear `DetectorReadout.tsx` con el código de §3.2.
4. Migrar `pages/HubPage.tsx` y `pages/ActivoPage.tsx` (las dos pantallas más usadas) aplicando §4, e integrar `DetectorReadout` en el rail derecho de `ActivoPage.tsx`.
5. Migrar `components/SignalCard.tsx`, `components/ChartHost.tsx`, `components/SignalCountdown.tsx`, `components/ParamForm.tsx` con la misma tabla.
6. Migrar `pages/BacktestPage.tsx`, `pages/EstrategiasPage.tsx`, `pages/ConfigPage.tsx`.
7. Revisión final: `npm run build` sin errores ni warnings nuevos, y un repaso visual (o de código) confirmando que ningún `bg-gray-*` ni `bg-blue-600` sobrevivió en `frontend/src/**/*.tsx`.

---

## 6. Criterios de aceptación

- [ ] `npm run build` termina sin error en cada paso del orden de ejecución, no solo al final.
- [ ] `grep -rn "bg-gray-\|text-gray-\|border-gray-\|bg-blue-600" frontend/src/` devuelve **cero resultados** al terminar.
- [ ] `signal-long`/`signal-short` (verde/rojo) aparecen **únicamente** en contextos de dirección de mercado real (señales, operaciones), verificable leyendo cada uso.
- [ ] Ningún archivo de `api.ts`, `store.ts`, ni las funciones `fetch*`/`use*` que consumen datos tienen diffs — el rediseño es puramente de JSX de presentación y clases CSS.
- [ ] Foco de teclado visible en todos los elementos interactivos (heredado automáticamente de `:focus-visible` en `index.css`, pero verificar que ningún componente lo sobreescriba con `outline-none` sin agregar un reemplazo).
- [ ] La app sigue siendo usable en una ventana angosta (verificar que el layout de 3 columnas de §2 colapsa razonablemente por debajo de ~1024px; no hace falta mobile-first perfecto, pero no puede romperse).

---

## 7. Lo que este agente NO debe hacer

- No agregar librerías de UI nuevas (Material UI, Chakra, shadcn, etc.) — todo se construye con Tailwind + los tokens de este documento, igual que ya está el proyecto.
- No modificar `App.tsx` más allá de lo estrictamente necesario para que el layout general (§2) funcione — el ruteo y la estructura de providers (`QueryClientProvider`, etc.) quedan igual.
- No "mejorar" ni renombrar funciones de `api.ts` o `store.ts` aunque el agente tenga una opinión sobre cómo están escritas — está fuera de alcance de esta tarea.
- No inventar campos de datos que no existan en las respuestas reales de la API (por ejemplo, para `DetectorReadout`, usar el campo real que ya devuelve `fetchSignals`, no asumir un shape).
