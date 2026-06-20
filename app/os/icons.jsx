/* Caripost OS — icon set + shared UI components */

const ICONS = {
  upload:'<path d="M12 16V4m0 0L7 9m5-5 5 5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  captions:'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M8.5 11a2 2 0 1 0 0 2M16 11a2 2 0 1 0 0 2"/>',
  analyze:'<circle cx="11" cy="11" r="6.5"/><path d="m20.5 20.5-4-4"/><path d="M11 8v6M8 11h6"/>',
  compare:'<path d="M12 3v18"/><path d="M7 7 3 12l4 5M17 7l4 5-4 5"/>',
  logo:'<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="8" cy="9" r="1.6"/><path d="m3.5 17 5-4.5 4 3 3-2.5 5 4"/>',
  teaser:'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10 9v6l5-3z"/>',
  post:'<path d="M5 3h10l4 4v14H5z"/><path d="M9 9h6M9 13h6M9 17h4"/>',
  calendar:'<rect x="3.5" y="5" width="17" height="16" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/><rect x="7" y="13" width="3.5" height="3.5" rx="1"/>',
  media:'<rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 6l2.4-2.6h6L14 6"/><circle cx="12" cy="12.5" r="3"/>',
  portal:'<circle cx="12" cy="8" r="3.4"/><path d="M5 20a7 7 0 0 1 14 0"/>',
  settings:'<circle cx="12" cy="12" r="3"/><path d="M12 3v2.4M12 18.6V21M4.5 7l2 1.2M17.5 15.8l2 1.2M19.5 7l-2 1.2M6.5 15.8l-2 1.2"/>',
  bolt:'<path d="M13 2 5 13h5l-1 9 8-11h-5z"/>',
  flow:'<circle cx="6" cy="6" r="2.4"/><circle cx="18" cy="6" r="2.4"/><circle cx="12" cy="18" r="2.4"/><path d="M8.2 6.5h7.6M7 8.4 11 15.6M17 8.4 13 15.6"/>',
  search:'<circle cx="11" cy="11" r="6.5"/><path d="m20.5 20.5-4-4"/>',
  bell:'<path d="M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6Z"/><path d="M10 19a2 2 0 0 0 4 0"/>',
  tasks:'<path d="M9 6h11M9 12h11M9 18h7"/><path d="m3.5 6 1.2 1.2L7 5M3.5 12l1.2 1.2L7 11"/>',
  check:'<path d="m5 12.5 4.5 4.5L20 6"/>',
  checkSm:'<path d="m4 8 3 3 5-6"/>',
  play:'<path d="M7 5v14l11-7z"/>',
  pause:'<path d="M8 5v14M16 5v14"/>',
  x:'<path d="M6 6l12 12M18 6 6 18"/>',
  min:'<path d="M5 12h14"/>',
  max:'<rect x="5" y="5" width="14" height="14" rx="2"/>',
  restore:'<rect x="7" y="7" width="11" height="11" rx="2"/><path d="M5 14V6a2 2 0 0 1 2-2h8"/>',
  help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.3 2.4c-.8.3-.8 1-.8 1.6M12 16.5v.1"/>',
  pen:'<path d="M4 20l1.2-4.2L16 5l3 3L8.2 18.8z"/><path d="M14 7l3 3"/>',
  arrowR:'<path d="M4 12h15m0 0-5-5m5 5-5 5"/>',
  arrowL:'<path d="M20 12H5m0 0 5-5m-5 5 5 5"/>',
  download:'<path d="M12 4v10m0 0 4-4m-4 4-4-4"/><path d="M5 18h14"/>',
  globe:'<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.5 2.4 2.5 14.6 0 17M12 3.5c-2.5 2.4-2.5 14.6 0 17"/>',
  copy:'<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M4 16V5a1 1 0 0 1 1-1h11"/>',
  link:'<path d="M9 15l6-6"/><path d="M11 7l1.5-1.5a4 4 0 0 1 5.6 5.6L16 13M13 17l-1.5 1.5a4 4 0 0 1-5.6-5.6L8 11"/>',
  star:'<path d="m12 3 2.6 5.6L20 9.3l-4 4 1 5.7L12 16l-5 3 1-5.7-4-4 5.4-.7z"/>',
  trash:'<path d="M5 7h14M9 7V5h6v2M7 7l1 12h8l1-12"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  filter:'<path d="M4 5h16l-6 7v6l-4 2v-8z"/>',
  clock:'<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>',
  layers:'<path d="m12 3 8.5 4.5L12 12 3.5 7.5z"/><path d="m3.5 12 8.5 4.5L20.5 12M3.5 16.5 12 21l8.5-4.5"/>',
  key:'<circle cx="8" cy="8" r="4"/><path d="m11 11 8 8M16 16l2-2M18.5 18.5l1.5-1.5"/>',
  send:'<path d="M21 3 10 14M21 3l-7 18-4-7-7-4z"/>',
  sparkles:'<path d="M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z"/><path d="M18 15l.7 1.8L20.5 17.5l-1.8.7L18 20l-.7-1.8L15.5 17.5l1.8-.7z"/>',
  drag:'<circle cx="9" cy="7" r="1.3"/><circle cx="15" cy="7" r="1.3"/><circle cx="9" cy="12" r="1.3"/><circle cx="15" cy="12" r="1.3"/><circle cx="9" cy="17" r="1.3"/><circle cx="15" cy="17" r="1.3"/>',
  eye:'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  chevR:'<path d="m9 6 6 6-6 6"/>',
  scissors:'<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M8 7.5 20 18M8 16.5 20 6"/>',
  wave:'<path d="M3 12h2l2-6 3 14 3-18 3 16 2-6h3"/>',
  // module icons
  runs:'<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 9h18M7 13h6M7 16.5h9"/><circle cx="6" cy="6.5" r=".6" fill="currentColor"/>',
  refs:'<circle cx="11" cy="11" r="6.5"/><path d="m20.5 20.5-4-4M11 8l1 2 2 .3-1.5 1.5.4 2-1.9-1-1.9 1 .4-2L8 10.3l2-.3z"/>',
  autoeditor:'<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3 9h18M8 5v4M16 5v4"/><path d="m10.5 12.5 4 2-4 2z" fill="currentColor"/>',
  enhance:'<path d="M5 12h3l2-7 3 14 2-7h4"/><path d="M19 4l.7 1.8L21.5 6.5l-1.8.7L19 9l-.7-1.8L16.5 6.5l1.8-.7z" fill="currentColor"/>',
  telegram:'<path d="M21 4 3 11l5 2 2 6 3-4 4 3z"/><path d="m8 13 8-6-5 7"/>',
  broadcast:'<circle cx="12" cy="12" r="2.4"/><path d="M7.5 7.5a6 6 0 0 0 0 9M16.5 7.5a6 6 0 0 1 0 9M5 5a9 9 0 0 0 0 14M19 5a9 9 0 0 1 0 14"/>',
  users:'<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M16 5.2a3 3 0 0 1 0 5.6M16.5 19a5.5 5.5 0 0 0-2-4.3"/>',
  trending:'<path d="M3 16l5-5 3 3 7-7"/><path d="M15 7h5v5"/>',
  dollar:'<circle cx="12" cy="12" r="8.5"/><path d="M12 7v10M14.5 9.3a2.6 2.6 0 0 0-2.5-1.3c-1.5 0-2.5.8-2.5 2s1 1.7 2.5 2 2.5.7 2.5 2-1 2-2.5 2a2.6 2.6 0 0 1-2.5-1.3"/>',
  shield:'<path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6z"/><path d="m9 12 2 2 4-4"/>',
  grid:'<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  list:'<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1" fill="currentColor"/><circle cx="4" cy="12" r="1" fill="currentColor"/><circle cx="4" cy="18" r="1" fill="currentColor"/>',
  recut:'<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M8 7.5 20 18M8 16.5 20 6"/><path d="M19 14a6 6 0 0 1-1 4"/>',
  doc:'<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 13h6M9 17h4"/>',
  mic:'<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M6 11a6 6 0 0 0 12 0M12 17v4M9 21h6"/>',
  money:'<rect x="3" y="6" width="18" height="12" rx="2.5"/><circle cx="12" cy="12" r="2.6"/><path d="M6 9v6M18 9v6"/>',
  shieldscan:'<path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6z"/><circle cx="11" cy="11" r="2.6"/><path d="m13 13 2 2"/>',
  warning:'<path d="M12 4 2.5 20h19z"/><path d="M12 10v4M12 17v.1"/>',
  refresh:'<path d="M4 12a8 8 0 0 1 14-5l2 2M20 12a8 8 0 0 1-14 5l-2-2"/><path d="M18 3v4h-4M6 21v-4h4"/>',
  gauge:'<path d="M5 18a8 8 0 1 1 14 0"/><path d="m12 14 4-4"/><circle cx="12" cy="14" r="1.4" fill="currentColor"/>',
  thumbnail:'<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="m3.5 16 5-4.5 3.5 3 3-2.5 5.5 4.5"/><circle cx="8" cy="9" r="1.5"/>',
  image:'<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="8.5" cy="9.5" r="1.8"/><path d="m3.5 17 5.5-5 4 3.5 3-2.5 5 4"/>',
  type:'<path d="M5 6h14M12 6v13M9 19h6"/>',
  burn:'<path d="M12 3c1.5 3-1.5 4 0 7 .8 1.6 3 1.5 3 4a3 3 0 0 1-6 .2C8.8 11.5 12 11 12 3z"/>',
  cortes:'<rect x="7" y="3" width="10" height="18" rx="2.5"/><path d="m10.5 9 4 3-4 3z"/>',
  building:'<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1"/>',
  radar:'<circle cx="12" cy="12" r="9"/><path d="M12 12 19 5"/><path d="M12 3v3M21 12h-3M12 21v-3M3 12h3"/><circle cx="12" cy="12" r="4"/>',
};

function Icon({ name, style }) {
  const p = ICONS[name] || '';
  return React.createElement('svg', {
    viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', style,
    dangerouslySetInnerHTML: { __html: p }
  });
}

/* ── shared bits ── */
function Pill({ kind, dot, icon, children }) {
  return <span className={'pill ' + (kind || '')}>
    {dot && <i className="dot" />}
    {icon && <Icon name={icon} />}
    {children}
  </span>;
}

function ProgressBar({ pct, eta, label, tone = '', indet }) {
  return <div className="prog">
    {(label || pct != null) && <div className="prog-head">
      <span>{label}</span>{pct != null && <b>{pct}%</b>}
    </div>}
    <div className={'track ' + tone + (indet ? ' indet' : '')}><i style={{ width: indet ? undefined : pct + '%' }} /></div>
    {eta && <div className="prog-eta">{eta}</div>}
  </div>;
}

function LogLines({ items }) {
  return <div className="log">
    {items.map((l, i) =>
      <div key={i} className={'logrow ' + (l.s || '')}>
        <span className="lk">
          {l.s === 'done' ? <Icon name="check" /> : l.s === 'now' ? <span className="spin" /> : <span style={{ width: 6, height: 6, borderRadius: 9, background: 'var(--faint)' }} />}
        </span>
        <span>{l.t}</span>
        {l.time && <time>{l.time}</time>}
      </div>
    )}
  </div>;
}

function Media({ ratio = '16/9', dur, cap, logo, subtitle, play = true, children }) {
  return <div className="media" style={{ aspectRatio: ratio }}>
    <div className="ph" />
    {play && <div className="play"><i><Icon name="play" /></i></div>}
    {dur && <span className="dur">{dur}</span>}
    {subtitle && <div className="subtitle-ov">{subtitle}</div>}
    {logo && <div className="logo-ov">LOGO</div>}
    {cap && <div className="cap"><span className="lbl-cap">{cap}</span></div>}
    {children}
  </div>;
}

/* Big video stage with player chrome — used for AutoEditor/Enhancer results */
function VStage({ ratio = '16/9', dur = '02:41', pos = 38, subtitle, logo, time = '01:02 / 02:41', children }) {
  return <div className="vstage" style={{ aspectRatio: ratio }}>
    <div className="ph" />
    {subtitle && <div className="subtitle-ov">{subtitle}</div>}
    {logo && <div className="logo-ov">LOGO</div>}
    <div className="center-play"><i><Icon name="play" /></i></div>
    {dur && <span className="dur">{dur}</span>}
    {children}
    <div className="vcontrols">
      <span className="pbtn"><Icon name="play" /></span>
      <div className="vbar"><i style={{ width: pos + '%' }} /></div>
      <span className="vtime">{time}</span>
    </div>
  </div>;
}

function Field({ label, children }) {
  return <div><label className="lbl">{label}</label>{children}</div>;
}

function Check({ on, onClick, children }) {
  return <button className={'checkx' + (on ? ' on' : '')} onClick={onClick}>
    <span className="bx"><Icon name="checkSm" /></span>{children}
  </button>;
}

function Switch({ on, onClick }) {
  return <span className={'sw' + (on ? ' on' : '')} onClick={onClick} />;
}

function Thumb({ label, sel, onClick }) {
  return <div className={'thumb' + (sel ? ' sel' : '')} onClick={onClick}>
    <div className="ph" />{label && <span className="t">{label}</span>}
  </div>;
}

Object.assign(window, { ICONS, Icon, Pill, ProgressBar, LogLines, Media, VStage, Field, Check, Switch, Thumb });
