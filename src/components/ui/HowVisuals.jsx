function num(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function Paper({ x = 44, y = 22, w = 40, h = 58 }) {
  const px = num(x, 44);
  const py = num(y, 22);
  const pw = num(w, 40);
  const ph = num(h, 58);

  return (
    <g>
      <rect x={px} y={py} width={pw} height={ph} rx="5" fill="#E8EEF5" />
      <rect x={px + 7} y={py + 14} width={pw - 14} height="3.5" rx="1.5" fill="#64748B" />
      <rect x={px + 7} y={py + 24} width={pw - 20} height="3.5" rx="1.5" fill="#7B8C9E" />
      <rect x={px + 7} y={py + 34} width={pw - 17} height="3.5" rx="1.5" fill="#7B8C9E" />
      {ph > 50 ? <rect x={px + 7} y={py + 44} width={pw - 22} height="3.5" rx="1.5" fill="#94A3B8" /> : null}
    </g>
  );
}

function Check({ x, y, size = 30, color = '#22C55E' }) {
  const s = num(size, 30);
  return (
    <svg x={num(x)} y={num(y)} width={s} height={s} viewBox="0 0 32 32">
      <circle cx="16" cy="16" r="16" fill={color} />
      <path
        d="M8.5 16.8 13.2 21.4 23.5 10.6"
        fill="none"
        stroke="#fff"
        strokeWidth="3.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function WhatsAppMark({ x, y, size = 28 }) {
  const s = num(size, 28);
  return (
    <svg x={num(x)} y={num(y)} width={s} height={s} viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="12" fill="#25D366" />
      <path
        fill="#fff"
        d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"
      />
    </svg>
  );
}

function ViberMark({ x, y, size = 28 }) {
  const s = num(size, 28);
  return (
    <svg x={num(x)} y={num(y)} width={s} height={s} viewBox="0 0 24 24">
      <rect width="24" height="24" rx="6.5" fill="#7360F2" />
      <g transform="translate(3.1 2.4) scale(0.74)">
        <path
          fill="#fff"
          fillRule="evenodd"
          d="M11.4 0C9.473.028 5.333.344 3.02 2.467 1.302 4.187.696 6.7.633 9.817.57 12.933.488 18.776 6.12 20.36h.003l-.004 2.416s-.037.977.61 1.177c.777.242 1.234-.5 1.98-1.302.407-.44.972-1.084 1.397-1.58 3.85.326 6.812-.416 7.15-.525.776-.252 5.176-.816 5.892-6.657.74-6.02-.36-9.83-2.34-11.546-.596-.55-3.006-2.3-8.375-2.323 0 0-.395-.025-1.037-.017zm.058 1.693c.545-.004.88.017.88.017 4.542.02 6.717 1.388 7.222 1.846 1.675 1.435 2.53 4.868 1.906 9.897v.002c-.604 4.878-4.174 5.184-4.832 5.395-.28.09-2.882.737-6.153.524 0 0-2.436 2.94-3.197 3.704-.12.12-.26.167-.352.144-.13-.033-.166-.188-.165-.414l.02-4.018c-4.762-1.32-4.485-6.292-4.43-8.895.054-2.604.543-4.738 1.996-6.173 1.96-1.773 5.474-2.018 7.11-2.03z"
        />
      </g>
    </svg>
  );
}

function SlackMark({ x, y, size = 28 }) {
  const s = num(size, 28);
  return (
    <svg x={num(x)} y={num(y)} width={s} height={s} viewBox="0 0 24 24">
      <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52z" fill="#E01E5A" />
      <path d="M6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313z" fill="#E01E5A" />
      <path d="M8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834z" fill="#36C5F0" />
      <path d="M8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312z" fill="#36C5F0" />
      <path d="M18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834z" fill="#2EB67D" />
      <path d="M17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312z" fill="#2EB67D" />
      <path d="M15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52z" fill="#ECB22E" />
      <path d="M15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z" fill="#ECB22E" />
    </svg>
  );
}

function MailMark({ x, y, size = 28 }) {
  const s = num(size, 28);
  return (
    <svg x={num(x)} y={num(y)} width={s} height={s} viewBox="0 0 24 24">
      <rect x="2" y="5" width="20" height="14" rx="2.2" fill="#7DD3FC" />
      <path d="M3 6.2 12 13l9-6.8" fill="none" stroke="#fff" strokeWidth="2.1" strokeLinejoin="round" />
      <path d="M3 18.2 9.4 12.2M21 18.2 14.6 12.2" fill="none" stroke="#38BDF8" strokeWidth="1.6" />
    </svg>
  );
}

function CaptureCluster() {
  return (
    <g>
      <Paper x={44} y={22} />
      <WhatsAppMark x={14} y={14} size={30} />
      <ViberMark x={86} y={12} size={30} />
      <SlackMark x={14} y={66} size={28} />
      <MailMark x={88} y={68} size={26} />
    </g>
  );
}

function Magnifier({ cx = 78, cy = 42, label }) {
  const lensX = num(cx, 78);
  const lensY = num(cy, 42);
  return (
    <g>
      <path
        d={`M${lensX + 16} ${lensY + 18} L${lensX + 34} ${lensY + 42}`}
        stroke="#64748B"
        strokeWidth="10"
        strokeLinecap="round"
      />
      <circle cx={lensX} cy={lensY} r="24" fill="#3B82F6" />
      <circle cx={lensX} cy={lensY} r="16" fill="#F8FAFC" />
      {label ? (
        <text
          x={lensX}
          y={lensY + 5}
          textAnchor="middle"
          fill="#2563EB"
          fontSize="13"
          fontWeight="800"
          fontFamily="Inter,system-ui,sans-serif"
        >
          {label}
        </text>
      ) : null}
    </g>
  );
}

function Gear({ x = 92, y = 58 }) {
  return (
    <g transform={`translate(${num(x, 92)} ${num(y, 58)})`}>
      {[0, 45, 90, 135].map((deg) => (
        <rect
          key={deg}
          x="-5"
          y="-22"
          width="10"
          height="44"
          rx="2.5"
          fill="#64748B"
          transform={`rotate(${deg})`}
        />
      ))}
      <circle r="14" fill="#64748B" />
      <circle r="6" fill="#E8EEF5" />
    </g>
  );
}

function Person({ x = 14, shirt = '#2563EB', hair = 'short' }) {
  const skin = '#F0C4A0';
  const hairFill = '#2A3A4D';

  return (
    <g transform={`translate(${num(x, 14)} 4)`}>
      <path fill={shirt} d="M6 104c1-26 12-40 26-40s25 14 26 40Z" />
      <path fill={skin} d="M27 54h10v14c-1.6 4.5-8.4 4.5-10 0Z" />
      <ellipse cx="32" cy="31" rx="18.5" ry="18.5" fill={hairFill} />
      {hair === 'long' ? (
        <>
          <path fill={hairFill} d="M14 34c-5 10-6 30-1 48 4 5 9 2 10-6 0-16 0-30 1-36-2-6-6-8-10-6Z" />
          <path fill={hairFill} d="M50 34c5 10 6 30 1 48-4 5-9 2-10-6 0-16 0-30-1-36 2-6 6-8 10-6Z" />
        </>
      ) : null}
      <ellipse cx="13.5" cy="40" rx="3.6" ry="4.8" fill={skin} />
      <ellipse cx="50.5" cy="40" rx="3.6" ry="4.8" fill={skin} />
      <circle cx="32" cy="38" r="16.5" fill={skin} />
    </g>
  );
}

function Phone({ x = 80, y = 26 }) {
  return (
    <g transform={`translate(${num(x, 80)} ${num(y, 26)}) rotate(-8)`}>
      <rect width="30" height="54" rx="7" fill="#0B1220" />
      <rect x="2.5" y="4.5" width="25" height="39" rx="3.5" fill="#BFDBFE" />
      <rect x="6" y="8.5" width="18" height="3.5" rx="1.6" fill="#2563EB" />
      <rect x="6" y="15" width="13" height="2.6" rx="1.2" fill="#60A5FA" />
      <rect x="6" y="20.5" width="16" height="2.6" rx="1.2" fill="#60A5FA" />
      <rect x="6" y="30" width="18" height="8" rx="2.2" fill="#2563EB" />
      <circle cx="15" cy="48.5" r="2.1" fill="#64748B" />
    </g>
  );
}

function MiniPerson({ cx, cy, color }) {
  const x = num(cx);
  const y = num(cy);
  return (
    <g>
      <circle cx={x} cy={y - 11} r="10" fill={color} />
      <path
        d={`M${x - 16} ${y + 24}C${x - 16} ${y + 6} ${x - 8} ${y} ${x} ${y}C${x + 8} ${y} ${x + 16} ${y + 6} ${x + 16} ${y + 24}Z`}
        fill={color}
      />
    </g>
  );
}

function Coin({ cx, cy, r = 16 }) {
  const x = num(cx);
  const y = num(cy);
  const radius = num(r, 16);
  const size = radius * 2;
  return (
    <svg x={x - radius} y={y - radius} width={size} height={size} viewBox="0 0 32 32">
      <circle cx="16" cy="16" r="15" fill="#FBBF24" />
      <circle cx="16" cy="16" r="12.5" fill="none" stroke="#F59E0B" strokeWidth="1.8" />
      <text
        x="16"
        y="17.5"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#7C4A03"
        fontSize="16"
        fontWeight="800"
        fontFamily="Inter,system-ui,sans-serif"
      >
        $
      </text>
    </svg>
  );
}

function Tag({ x, y, w, fill, label }) {
  const px = num(x);
  const py = num(y);
  return (
    <g>
      <rect x={px} y={py} width={num(w)} height="16" rx="4" fill={fill} />
      <text
        x={px + 6}
        y={py + 11.5}
        fill="#fff"
        fontSize="8"
        fontWeight="700"
        fontFamily="Inter,system-ui,sans-serif"
      >
        {label}
      </text>
    </g>
  );
}

function Scene({ children }) {
  return (
    <svg viewBox="0 0 128 108" aria-hidden="true">
      {children}
    </svg>
  );
}

const visuals = {
  capture: (
    <Scene>
      <CaptureCluster />
    </Scene>
  ),
  analyse: (
    <Scene>
      <Paper x={16} y={20} />
      <Magnifier cx={84} cy={44} label="AI" />
    </Scene>
  ),
  classify: (
    <Scene>
      <Paper x={14} y={16} w={46} h={76} />
      <Tag x={52} y={20} w={62} fill="#3B82F6" label="Invoice" />
      <Tag x={52} y={40} w={62} fill="#22C55E" label="Receipt" />
      <Tag x={52} y={60} w={62} fill="#F59E0B" label="Statement" />
      <Tag x={52} y={80} w={68} fill="#8B5CF6" label="Supporting File" />
    </Scene>
  ),
  extract: (
    <Scene>
      <Paper x={20} y={16} />
      <Check x={68} y={56} size={36} />
      <g transform="translate(92 24)">
        <path
          d="M8 6c0-4 4-6 7-6s7 2 7 6v22c0 5-4 8-8 8s-8-3-8-8V14c0-3 2-5 5-5s5 2 5 5v16"
          fill="none"
          stroke="#60A5FA"
          strokeWidth="4"
          strokeLinecap="round"
        />
      </g>
    </Scene>
  ),
  rules: (
    <Scene>
      <Paper x={14} y={18} />
      <Gear x={96} y={60} />
    </Scene>
  ),
  budget: (
    <Scene>
      <rect x={36} y={10} width={56} height={14} rx="4" fill="#CBD5E1" />
      <rect x={46} y={6} width={36} height={18} rx="4" fill="#94A3B8" />
      <rect x={32} y={18} width={64} height={78} rx="6" fill="#E8EEF5" />
      <Check x={42} y={32} size={22} />
      <Check x={42} y={56} size={22} />
      <Check x={42} y={80} size={22} />
      <rect x={70} y={38} width={18} height={4} rx="2" fill="#64748B" />
      <rect x={70} y={62} width={18} height={4} rx="2" fill="#64748B" />
      <rect x={70} y={86} width={18} height={4} rx="2" fill="#64748B" />
    </Scene>
  ),
  coding: (
    <Scene>
      <rect x={22} y={18} width={52} height={72} rx="6" fill="#E8EEF5" />
      <rect x={30} y={28} width={36} height={3.5} rx="1.5" fill="#64748B" />
      <rect x={30} y={38} width={28} height={3.5} rx="1.5" fill="#94A3B8" />
      <rect x={32} y={58} width={10} height={22} rx="2" fill="#22C55E" />
      <rect x={46} y={46} width={10} height={34} rx="2" fill="#3B82F6" />
      <rect x={60} y={34} width={10} height={46} rx="2" fill="#F59E0B" />
      <circle cx={96} cy={36} r={18} fill="#8B5CF6" />
      <path d="M96 26v20M86 36h20" stroke="#fff" strokeWidth="4" strokeLinecap="round" />
    </Scene>
  ),
  validate: (
    <Scene>
      <Paper x={18} y={16} />
      <Check x={72} y={52} size={42} />
    </Scene>
  ),
  sync: (
    <Scene>
      <rect x={26} y={58} width={76} height={28} rx={14} fill="#38BDF8" />
      <circle cx={42} cy={58} r={22} fill="#38BDF8" />
      <circle cx={64} cy={48} r={28} fill="#38BDF8" />
      <circle cx={90} cy={56} r={20} fill="#38BDF8" />
      <path d="M64 38v36" stroke="#fff" strokeWidth="5" strokeLinecap="round" />
      <path d="M54 50l10-12 10 12M54 66l10 12 10-12" stroke="#fff" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
    </Scene>
  ),
  archive: (
    <Scene>
      <path d="M18 40h32l8 10h52v42H18V40Z" fill="#FBBF24" />
      <path d="M18 40h30l7 10H18V40Z" fill="#F59E0B" />
      <g transform="rotate(-8 64 39)">
        <Paper x={48} y={16} w={32} h={44} />
      </g>
    </Scene>
  ),
  raise: (
    <Scene>
      <Person x={10} shirt="#2563EB" />
      <Phone x={78} y={24} />
    </Scene>
  ),
  supervisor: (
    <Scene>
      <Person x={8} shirt="#16A34A" />
      <Check x={86} y={30} size={36} />
    </Scene>
  ),
  finance: (
    <Scene>
      <Person x={8} shirt="#7C3AED" hair="long" />
      <Check x={86} y={30} size={36} color="#7C3AED" />
    </Scene>
  ),
  funds: (
    <Scene>
      <polygon points="64,12 18,36 110,36" fill="#2563EB" />
      <rect x={22} y={36} width={84} height={8} fill="#1D4ED8" />
      <rect x={30} y={48} width={12} height={34} fill="#60A5FA" />
      <rect x={50} y={48} width={12} height={34} fill="#60A5FA" />
      <rect x={70} y={48} width={12} height={34} fill="#60A5FA" />
      <rect x={90} y={48} width={12} height={34} fill="#60A5FA" />
      <rect x={22} y={82} width={84} height={10} fill="#1D4ED8" />
      <Coin cx={108} cy={26} r={15} />
    </Scene>
  ),
  upload: (
    <Scene>
      <Paper x={36} y={12} w={48} h={70} />
      <rect x={36} y={12} width={48} height={16} rx="5" fill="#3B82F6" />
      <rect x={36} y={20} width={48} height={8} fill="#3B82F6" />
      <text
        x={60}
        y={24}
        textAnchor="middle"
        fill="#fff"
        fontSize="8"
        fontWeight="800"
        fontFamily="Inter,system-ui,sans-serif"
      >
        INVOICE
      </text>
      <circle cx={88} cy={80} r={20} fill="#22C55E" />
      <path d="M88 90V70M78 78l10-10 10 10" stroke="#fff" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
    </Scene>
  ),
  checks: (
    <Scene>
      <path d="M78 70 104 98" stroke="#3B82F6" strokeWidth="11" strokeLinecap="round" />
      <circle cx={56} cy={48} r={32} fill="#3B82F6" />
      <circle cx={56} cy={48} r={22} fill="#F8FAFC" />
      <path
        d="M46 49 53 56 68 40"
        fill="none"
        stroke="#22C55E"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Scene>
  ),
  routed: (
    <Scene>
      <path d="M64 38v18M64 56H28v12M64 56h36v12" stroke="#94A3B8" strokeWidth="3" strokeLinecap="round" />
      <MiniPerson cx={64} cy={26} color="#F59E0B" />
      <MiniPerson cx={28} cy={86} color="#3B82F6" />
      <MiniPerson cx={64} cy={86} color="#8B5CF6" />
      <MiniPerson cx={100} cy={86} color="#22C55E" />
    </Scene>
  ),
  payment: (
    <Scene>
      <rect x={34} y={14} width={52} height={40} rx="6" fill="#93C5FD" />
      <rect x={40} y={22} width={26} height="5" rx="2.5" fill="#2563EB" />
      <rect x={40} y={32} width={16} height="4" rx="2" fill="#60A5FA" />
      <rect x={16} y={46} width={84} height={52} rx="12" fill="#2563EB" />
      <path d="M16 58c0-8 5-12 12-12h60c7 0 12 4 12 12v8H16V58Z" fill="#1D4ED8" />
      <rect x={74} y={68} width={16} height={12} rx="6" fill="#93C5FD" />
      <Coin cx={108} cy={28} r={16} />
    </Scene>
  ),
  captureFiles: (
    <Scene>
      <CaptureCluster />
    </Scene>
  ),
  routeFolder: (
    <Scene>
      <path d="M14 42h30l8 10h62v40H14V42Z" fill="#FBBF24" />
      <path d="M14 42h28l7 10H14V42Z" fill="#F59E0B" />
      <Paper x={48} y={18} w={32} h={44} />
      <Check x={86} y={12} size={34} />
    </Scene>
  ),
  timestamp: (
    <Scene>
      <Paper x={14} y={18} />
      <rect x={72} y={24} width={42} height={52} rx="6" fill="#E8EEF5" />
      <rect x={72} y={24} width={42} height={14} fill="#EF4444" />
      <circle cx={93} cy={58} r={13} fill="#3B82F6" />
      <path d="M93 51v8h6" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" />
    </Scene>
  ),
  organize: (
    <Scene>
      <path d="M46 8h32l7 8h22v20H38V16l8-8Z" fill="#3B82F6" />
      <path d="M64 36v14M22 50h84" stroke="#94A3B8" strokeWidth="3" strokeLinecap="round" />
      <path d="M22 50v10M64 50v10M106 50v10" stroke="#94A3B8" strokeWidth="3" strokeLinecap="round" />
      <path d="M6 60h22l5 6h8v24H6V60Z" fill="#FBBF24" />
      <path d="M48 60h22l5 6h8v24H48V60Z" fill="#FBBF24" />
      <path d="M90 60h22l5 6h8v24H90V60Z" fill="#FBBF24" />
    </Scene>
  ),
  companion: (
    <Scene>
      <Paper x={14} y={18} />
      <Magnifier cx={86} cy={48} />
    </Scene>
  ),
  bundle: (
    <Scene>
      <Paper x={8} y={20} w={44} h={66} />
      <rect x={76} y={26} width={44} height={66} rx="5" fill="#EDE9FE" />
      <rect x={84} y={40} width={28} height={3.5} rx="1.5" fill="#7C3AED" />
      <rect x={84} y={50} width={22} height={3.5} rx="1.5" fill="#A78BFA" />
      <rect x={84} y={60} width={26} height={3.5} rx="1.5" fill="#A78BFA" />
      <g transform="translate(64 54) rotate(-28)">
        <rect x="-18" y="-8" width="24" height="16" rx="8" fill="none" stroke="#22C55E" strokeWidth="4.5" />
        <rect x="-4" y="-8" width="24" height="16" rx="8" fill="none" stroke="#22C55E" strokeWidth="4.5" />
      </g>
    </Scene>
  ),
  update: (
    <Scene>
      <Paper x={14} y={18} w={44} h={70} />
      <circle cx={25} cy={72} r={5} fill="#22C55E" />
      <circle cx={38} cy={72} r={5} fill="#3B82F6" />
      <circle cx={51} cy={72} r={5} fill="#F59E0B" />
      <svg x={74} y={24} width={48} height={48} viewBox="0 0 24 24">
        <path
          d="M21 12a9 9 0 1 1-2.6-6.4"
          fill="none"
          stroke="#3B82F6"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
        <path
          d="M21 3v6h-6"
          fill="none"
          stroke="#3B82F6"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </Scene>
  ),
  report: (
    <Scene>
      <rect x={16} y={22} width={64} height={68} rx="6" fill="#E8EEF5" />
      <rect x={26} y={32} width={44} height={3.5} rx="1.5" fill="#64748B" />
      <rect x={28} y={56} width={10} height={24} rx="2" fill="#3B82F6" />
      <rect x={43} y={44} width={10} height={36} rx="2" fill="#22C55E" />
      <rect x={58} y={34} width={10} height={46} rx="2" fill="#F59E0B" />
      <path d="M96 18c12 0 18 10 18 20 0 14-10 18-10 28H86c0-10-10-14-10-28 0-10 6-20 20-20Z" fill="#FBBF24" />
      <circle cx={96} cy={78} r={6} fill="#FBBF24" />
    </Scene>
  ),
};

export default function HowVisual({ name }) {
  return <div className="how-step-visual">{visuals[name]}</div>;
}
