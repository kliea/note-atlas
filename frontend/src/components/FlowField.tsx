/* Decorative airflow behind the workspace. Hidden from assistive tech. */
export function FlowField() {
  return (
    <div className="flow-field" aria-hidden="true">
      <svg className="flow-svg" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice">
        <defs>
          <linearGradient id="flow-ribbon-a" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--flow-c)" stopOpacity="0.2" />
            <stop offset="0.45" stopColor="var(--flow-a)" stopOpacity="0.95" />
            <stop offset="1" stopColor="var(--flow-d)" stopOpacity="0.35" />
          </linearGradient>
          <linearGradient id="flow-ribbon-b" x1="1" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--flow-a)" stopOpacity="0.1" />
            <stop offset="0.5" stopColor="var(--flow-c)" stopOpacity="0.75" />
            <stop offset="1" stopColor="var(--flow-d)" stopOpacity="0.25" />
          </linearGradient>
          <linearGradient id="flow-ribbon-c" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" stopColor="var(--flow-d)" stopOpacity="0.15" />
            <stop offset="0.55" stopColor="var(--flow-b)" stopOpacity="0.55" />
            <stop offset="1" stopColor="var(--flow-c)" stopOpacity="0.1" />
          </linearGradient>
        </defs>
        <path
          className="flow-ribbon flow-ribbon-a"
          fill="url(#flow-ribbon-a)"
          d="M-80 250C180 140 360 390 640 300C940 200 1120 360 1540 220L1540 430C1140 560 900 280 600 470C280 670 80 420-80 520Z"
        />
        <path
          className="flow-ribbon flow-ribbon-b"
          fill="url(#flow-ribbon-b)"
          d="M-120 480C160 360 420 620 720 500C1020 380 1220 560 1560 430L1560 640C1180 760 860 500 540 680C240 850 40 640-120 740Z"
        />
        <path
          className="flow-ribbon flow-ribbon-c"
          fill="url(#flow-ribbon-c)"
          d="M-40 120C220 40 480 240 760 150C1040 60 1260 200 1520 90L1520 250C1200 360 920 140 600 300C280 460 80 240-40 340Z"
        />
      </svg>
    </div>
  );
}
