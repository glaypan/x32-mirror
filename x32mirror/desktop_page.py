"""macOS-style desktop UI page (served at /desktop by webui.py).

Design language: Apple HIG minimalism (vibrancy materials, SF type, dynamic
light/dark, accent colors) with a **card workspace** as the primary
interaction model: consoles, sync modes and quick actions are all large
tap-target cards, so the common flows are one click away.

Pages: 工作台 (card workspace) / 连接 / 热备 / 备份 / 日志 / 帮助.
Works in any modern browser; traffic-light window buttons activate only
inside the pywebview shell (see desktop.py).
"""

DESKTOP_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="data:,">
<title>x32-mirror 调音台同步</title>
<style>
/* ============================== tokens ============================== */
:root{
  --accent:#0a84ff; --accent-ink:#fff;
  --ease:cubic-bezier(.25,1,.5,1);      /* ease-out-quart */
  --r-lg:16px; --r-md:11px; --r-sm:8px;
  --sidebar-w:216px;
  --font:-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display","Helvetica Neue","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Segoe UI",sans-serif;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
}
/* light (default) */
:root{
  --ink:#1d1d1f; --ink-2:#6e6e73; --ink-3:#a1a1a6;
  --mat:rgba(246,246,249,.72);            /* vibrancy material */
  --mat-strong:rgba(255,255,255,.86);
  --fill:rgba(120,120,128,.10); --fill-2:rgba(120,120,128,.06);
  --fill-3:rgba(120,120,128,.16);
  --line:rgba(0,0,0,.09); --line-2:rgba(0,0,0,.05);
  --card:#fff; --card-2:#fbfbfd;
  --shadow:0 1px 2px rgba(0,0,0,.05),0 10px 32px rgba(0,0,0,.07);
  --led-on:#28cd41; --led-warn:#ff9f0a; --led-err:#ff453a; --led-off:#c7c7cc;
  --console-bg:#14161a; --console-ink:#e8eaed; --console-ink-2:#9aa0a6;
  --wall-1:#dfe6f2; --wall-2:#f2e6ee; --wall-3:#e6f2ec;
}
/* dark via system preference (no manual override) */
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ink:#f5f5f7; --ink-2:#a1a1a6; --ink-3:#6e6e73;
    --mat:rgba(30,30,34,.66); --mat-strong:rgba(38,38,44,.82);
    --fill:rgba(255,255,255,.09); --fill-2:rgba(255,255,255,.05); --fill-3:rgba(255,255,255,.14);
    --line:rgba(255,255,255,.12); --line-2:rgba(255,255,255,.06);
    --card:#1e1e22; --card-2:#26262b;
    --shadow:0 1px 2px rgba(0,0,0,.3),0 12px 36px rgba(0,0,0,.4);
    --led-off:#48484a;
    --wall-1:#10131c; --wall-2:#1a1220; --wall-3:#0e1a16;
  }
}
/* manual override wins */
:root[data-theme="dark"]{
  --ink:#f5f5f7; --ink-2:#a1a1a6; --ink-3:#6e6e73;
  --mat:rgba(30,30,34,.66); --mat-strong:rgba(38,38,44,.82);
  --fill:rgba(255,255,255,.09); --fill-2:rgba(255,255,255,.05); --fill-3:rgba(255,255,255,.14);
  --line:rgba(255,255,255,.12); --line-2:rgba(255,255,255,.06);
  --card:#1e1e22; --card-2:#26262b;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 12px 36px rgba(0,0,0,.4);
  --led-off:#48484a;
  --wall-1:#10131c; --wall-2:#1a1220; --wall-3:#0e1a16;
}
/* ============================== base ============================== */
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{
  font-family:var(--font); color:var(--ink); font-size:13px; line-height:1.5;
  -webkit-font-smoothing:antialiased; overflow:hidden;
  background:var(--wall-1);
}
button{font-family:inherit;color:inherit;background:none;border:0;cursor:pointer}
input,select{font-family:inherit;font-size:13px;color:var(--ink)}
::selection{background:color-mix(in srgb,var(--accent) 30%,transparent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:1px;border-radius:4px}

/* wallpaper */
#wall{position:fixed;inset:0;z-index:-2;
  background:
    radial-gradient(52% 42% at 18% 12%, var(--wall-1) 0%, transparent 70%),
    radial-gradient(46% 46% at 84% 22%, var(--wall-2) 0%, transparent 72%),
    radial-gradient(60% 55% at 55% 96%, var(--wall-3) 0%, transparent 70%),
    linear-gradient(160deg, var(--wall-1), var(--wall-2) 55%, var(--wall-3));
  transition:background .6s var(--ease);
}
#wall::after{content:"";position:absolute;inset:0;backdrop-filter:blur(2px)}

/* ============================== layout ============================== */
#app{display:grid;grid-template-columns:var(--sidebar-w) minmax(0,1fr);grid-template-rows:minmax(0,1fr);height:100vh;overflow:hidden}

/* ---- sidebar (vibrancy) ---- */
#side{
  position:relative;display:flex;flex-direction:column;min-height:0;overflow-y:auto;
  background:var(--mat); -webkit-backdrop-filter:blur(28px) saturate(1.7); backdrop-filter:blur(28px) saturate(1.7);
  border-right:1px solid var(--line);
  padding: max(38px, env(safe-area-inset-top)) 12px 12px;
}
#lights{position:absolute;top:14px;left:14px;display:none;gap:8px}
#lights button{width:12px;height:12px;border-radius:50%;position:relative;transition:filter .15s}
#lights button:hover{filter:brightness(1.15)}
#lights .l-close{background:#ff5f57;box-shadow:inset 0 0 0 .5px rgba(0,0,0,.15)}
#lights .l-min{background:#febc2e;box-shadow:inset 0 0 0 .5px rgba(0,0,0,.15)}
#lights .l-max{background:#28c840;box-shadow:inset 0 0 0 .5px rgba(0,0,0,.15)}
#lights button svg{position:absolute;inset:2px;opacity:0;transition:opacity .12s}
#lights:hover button svg{opacity:.55}
#brand{display:flex;align-items:center;gap:9px;padding:4px 8px 14px;font-weight:700;font-size:13.5px;letter-spacing:-.01em}
#brand .logo{width:22px;height:22px;border-radius:6px;background:linear-gradient(145deg,var(--accent),color-mix(in srgb,var(--accent) 55%,#000));
  display:grid;place-items:center;color:#fff;box-shadow:0 2px 8px color-mix(in srgb,var(--accent) 45%,transparent)}
nav{display:flex;flex-direction:column;gap:2px}
nav button{
  display:flex;align-items:center;gap:9px;padding:6px 10px;border-radius:var(--r-sm);
  font-size:13px;color:var(--ink);text-align:left;transition:background .15s var(--ease);
}
nav button svg{flex:none;color:var(--accent)}
nav button:hover{background:var(--fill)}
nav button.sel{background:var(--accent);color:var(--accent-ink);font-weight:600}
nav button.sel svg{color:var(--accent-ink)}
#side .spacer{flex:1}
#enginePill{
  display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:var(--r-sm);
  background:var(--fill-2);border:1px solid var(--line-2);font-size:12px;color:var(--ink-2);
}
#enginePill b{color:var(--ink);font-weight:600}

/* ---- main ---- */
#main{display:flex;flex-direction:column;min-width:0;min-height:0;background:var(--mat-strong);
  -webkit-backdrop-filter:blur(36px) saturate(1.6); backdrop-filter:blur(36px) saturate(1.6);}
#bar{display:flex;align-items:center;gap:12px;padding:14px 28px 10px;min-height:52px;flex:none}
#bar h1{font-size:17px;font-weight:700;letter-spacing:-.02em;margin-right:auto;display:flex;align-items:center;gap:10px}
#bar h1 small{font-size:12px;font-weight:500;color:var(--ink-2)}
/* the ONLY scroll container: capped by the grid row above, scrolls its content */
#content{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:6px 28px 34px;scrollbar-width:thin}
.page{display:none;animation:pageIn .32s var(--ease)}
.page.on{display:block}
@keyframes pageIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* ============================== components ============================== */
/* macOS push buttons */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;height:28px;padding:0 14px;
  border-radius:var(--r-sm);font-size:13px;font-weight:500;background:var(--card);border:1px solid var(--line);
  box-shadow:0 .5px 1.5px rgba(0,0,0,.08);transition:transform .12s var(--ease),background .15s,filter .15s;white-space:nowrap}
.btn:hover{filter:brightness(.97)} .btn:active{transform:scale(.97);filter:brightness(.94)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .btn{background:var(--fill-3);border-color:var(--line);box-shadow:none}}
.btn.primary{background:var(--accent);border-color:transparent;color:var(--accent-ink);font-weight:600;
  box-shadow:0 2px 10px color-mix(in srgb,var(--accent) 40%,transparent)}
.btn.danger{background:var(--led-err);border-color:transparent;color:#fff;font-weight:600}
.btn.plain{background:transparent;border-color:transparent;box-shadow:none;color:var(--accent);font-weight:500}
.btn.plain:hover{background:var(--fill)}
.btn[disabled]{opacity:.45;pointer-events:none}
.btn.big{height:34px;padding:0 18px;font-size:13.5px}
.btn svg{flex:none}

/* macOS switch */
.sw{position:relative;width:40px;height:24px;flex:none;cursor:pointer}
.sw input{position:absolute;opacity:0;pointer-events:none}
.sw i{position:absolute;inset:0;border-radius:12px;background:var(--fill-3);transition:background .25s var(--ease)}
.sw i::after{content:"";position:absolute;top:2px;left:2px;width:20px;height:20px;border-radius:50%;
  background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.3);transition:transform .25s var(--ease)}
.sw input:checked+i{background:var(--led-on)}
.sw input:checked+i::after{transform:translateX(16px)}

/* segmented control */
.seg{display:inline-flex;background:var(--fill);border-radius:9px;padding:2px;gap:2px}
.seg button{padding:3px 14px;border-radius:7px;font-size:12.5px;color:var(--ink-2);transition:all .18s var(--ease)}
.seg button.sel{background:var(--card);color:var(--ink);font-weight:600;box-shadow:0 .5px 2px rgba(0,0,0,.12)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .seg button.sel{background:var(--fill-3);box-shadow:none}}

/* form rows (macOS settings style) */
.group{background:var(--card);border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:var(--shadow);
  margin-bottom:18px;overflow:hidden}
.group>.gh{padding:11px 16px 4px;font-size:12px;font-weight:600;color:var(--ink-2);letter-spacing:.01em}
.row{display:flex;align-items:center;gap:14px;padding:10px 16px;border-top:1px solid var(--line-2);min-height:42px}
.row:first-of-type{border-top:0}
.row .lab{flex:0 0 128px;font-size:13px;color:var(--ink)}
.row .lab small{display:block;font-size:11px;color:var(--ink-3);font-weight:400}
.row .val{flex:1;display:flex;align-items:center;gap:8px;min-width:0;justify-content:flex-end}
.field{width:100%;max-width:260px;height:26px;padding:0 9px;border-radius:6px;border:1px solid var(--line);
  background:var(--card-2);transition:border-color .15s,box-shadow .15s;text-align:right}
.field:focus{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 22%,transparent);outline:none}
select.field{text-align:left}
.row.note{border-top:0;padding-top:0;color:var(--ink-3);font-size:11.5px;justify-content:flex-end}

/* cards */
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:var(--shadow);padding:16px}
.grid{display:grid;gap:18px}
.g2{grid-template-columns:1fr 1fr}
@media (max-width:980px){.g2{grid-template-columns:1fr}}

/* LED + status text */
.led{width:9px;height:9px;border-radius:50%;background:var(--led-off);flex:none;transition:background .3s}
.led.on{background:var(--led-on);box-shadow:0 0 8px color-mix(in srgb,var(--led-on) 70%,transparent);animation:ledPulse 2.4s infinite}
.led.warn{background:var(--led-warn);box-shadow:0 0 8px color-mix(in srgb,var(--led-warn) 70%,transparent)}
.led.err{background:var(--led-err);box-shadow:0 0 8px color-mix(in srgb,var(--led-err) 70%,transparent);animation:ledPulse 1s infinite}
.led.big{width:11px;height:11px}
@keyframes ledPulse{0%,100%{opacity:1}50%{opacity:.55}}

/* ============ card workspace (home) ============ */
.sect{margin-bottom:20px}
.sect>.sh{display:flex;align-items:center;gap:10px;margin:2px 2px 13px;flex-wrap:wrap}
.sect>.sh .n{font-family:var(--mono);font-size:11px;font-weight:700;color:var(--accent);
  background:color-mix(in srgb,var(--accent) 12%,transparent);border-radius:6px;padding:2px 8px;letter-spacing:.04em}
.sect>.sh .t{font-size:15px;font-weight:700;letter-spacing:-.01em}
.sect>.sh .s{font-size:11.5px;color:var(--ink-3)}
.sect>.sh .acts{margin-left:auto;display:flex;align-items:center;gap:8px}

.badge{font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:9px;background:var(--fill);color:var(--ink-2);letter-spacing:.03em;white-space:nowrap}
.badge.ok{background:color-mix(in srgb,var(--led-on) 16%,transparent);color:var(--led-on)}
.badge.warn{background:color-mix(in srgb,var(--led-warn) 16%,transparent);color:var(--led-warn)}
.badge.err{background:color-mix(in srgb,var(--led-err) 14%,transparent);color:var(--led-err)}

/* console cards */
.congrid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:980px){.congrid{grid-template-columns:1fr}}
.concard{background:var(--card);border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:var(--shadow);
  padding:18px 20px;display:flex;flex-direction:column;gap:13px;transition:opacity .25s}
.concard.off{opacity:.72}
.concard .head{display:flex;align-items:center;gap:10px}
.concard .head .nm{font-weight:700;font-size:16px;letter-spacing:-.01em}
.concard .head .badge{margin-left:auto}
.concard .info{font-family:var(--mono);font-size:11.5px;color:var(--ink-2);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-height:17px}
.concard .addr{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--ink-2)}
.concard .addr .field{width:128px;height:26px;font-size:12px;text-align:left}
.concard .addr .field.sm{width:64px}
.concard .meters{display:flex;flex-direction:column;gap:7px}
.meter{display:grid;grid-template-columns:64px 1fr 52px;align-items:center;gap:9px;font-size:11px;color:var(--ink-2)}
.meter .track{height:5px;border-radius:3px;background:var(--fill);overflow:hidden}
.meter .fill{height:100%;width:0;border-radius:3px;background:linear-gradient(90deg,var(--accent),color-mix(in srgb,var(--accent) 60%,#fff));
  transition:width .5s var(--ease)}
.meter b{font-family:var(--mono);font-weight:500;text-align:right;color:var(--ink);font-variant-numeric:tabular-nums}

/* mode cards — the primary selection */
.modes{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
@media (max-width:980px){.modes{grid-template-columns:1fr}}
.modecard{position:relative;text-align:left;background:var(--card);border:1.5px solid var(--line);
  border-radius:var(--r-lg);box-shadow:var(--shadow);padding:16px 17px 14px;display:flex;flex-direction:column;gap:8px;
  min-height:128px;transition:transform .16s var(--ease),border-color .18s,background .18s,box-shadow .18s}
.modecard:hover{transform:translateY(-2px);box-shadow:0 2px 3px rgba(0,0,0,.05),0 16px 44px rgba(0,0,0,.10)}
.modecard:active{transform:scale(.985)}
.modecard .glyph{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--ink-2);
  background:var(--fill);border-radius:8px;padding:4px 11px;align-self:flex-start;letter-spacing:.04em}
.modecard b{font-size:15px;letter-spacing:-.01em}
.modecard small{font-size:12px;color:var(--ink-2);line-height:1.7}
.modecard.sel{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 7%,var(--card))}
.modecard.sel .glyph{background:var(--accent);color:var(--accent-ink)}
.modecard.sel::after{content:"✓";position:absolute;top:12px;right:14px;color:var(--accent);font-weight:700;font-size:14px}
.modenote{margin-top:13px;font-size:11.5px;color:var(--ink-3);line-height:1.8}
.modenote b{color:var(--ink-2);font-weight:600}

/* run status card — "可以操作调音台" + link counters */
.runcard{background:var(--card);border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:var(--shadow);
  padding:15px 18px 12px;display:flex;flex-direction:column;gap:11px}
.runcard .rc-top{display:flex;align-items:flex-start;gap:12px}
.runcard .rc-t{font-size:14.5px;font-weight:700;letter-spacing:-.01em;display:flex;align-items:center;gap:9px}
.runcard .rc-sub{font-size:11.5px;color:var(--ink-3);margin-top:5px}
.runcard .rc-acts{margin-left:auto;display:flex;gap:8px;flex:none}
.runcard .rc-bot{display:flex;align-items:center;gap:16px;border-top:1px solid var(--line-2);padding-top:10px;flex-wrap:wrap}
.runcard .rc-stats{display:flex;gap:20px;flex-wrap:wrap;font-size:11.5px;color:var(--ink-2)}
.runcard .rc-stats b{font-family:var(--mono);font-size:13.5px;color:var(--ink);font-weight:600;margin-left:5px;font-variant-numeric:tabular-nums}
.runcard .rc-stats .hot b{color:var(--accent)}
.runcard .rc-stats .bad b{color:var(--led-warn)}
.runcard.paused{border-color:color-mix(in srgb,var(--led-warn) 40%,var(--line))}
.runcard.paused .rc-t{color:var(--led-warn)}

/* safety-check progress dialog */
#jobBg{position:fixed;inset:0;z-index:60;display:grid;place-items:center;padding:24px;
  background:rgba(0,0,0,.30);-webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);
  opacity:0;pointer-events:none;transition:opacity .2s var(--ease)}
#jobBg.on{opacity:1;pointer-events:auto}
#jobDlg{width:min(540px,92vw);background:var(--mat-strong);
  -webkit-backdrop-filter:blur(40px) saturate(1.8);backdrop-filter:blur(40px) saturate(1.8);
  border:1px solid var(--line);border-radius:18px;box-shadow:0 26px 80px rgba(0,0,0,.36);
  padding:22px 24px 16px;transform:translateY(12px) scale(.985);transition:transform .26s var(--ease)}
#jobBg.on #jobDlg{transform:none}
#jobDlg h3{font-size:15.5px;font-weight:700;letter-spacing:-.01em;margin-bottom:9px}
#jobDlg p{font-size:12.5px;color:var(--ink-2);line-height:1.75;margin-bottom:14px}
#jobDlg .jtarget{font-size:12.5px;font-weight:600;margin-bottom:11px;color:var(--ink)}
#jobDlg .pbar{position:relative;height:9px;border-radius:5px;background:var(--fill);overflow:hidden;margin-bottom:11px}
#jobDlg .pbar i{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:5px;
  background:linear-gradient(90deg,var(--accent),color-mix(in srgb,var(--accent) 55%,#fff));
  transition:width .28s var(--ease)}
#jobDlg .jline{font-family:var(--mono);font-size:11.5px;color:var(--ink-2);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:7px}
#jobDlg .jnote{font-size:11px;color:var(--ink-3);margin-bottom:16px}
#jobDlg .jdone{font-size:12.5px;font-weight:600;margin-bottom:10px;display:none}
#jobDlg .jacts{display:flex;justify-content:flex-end;gap:10px}

/* quick action cards */
.quick{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:14px}
.qcard{display:flex;align-items:center;gap:13px;text-align:left;background:var(--card);border:1px solid var(--line);
  border-radius:var(--r-lg);box-shadow:var(--shadow);padding:16px 18px;min-height:66px;
  transition:transform .16s var(--ease),filter .15s,border-color .18s}
.qcard:hover{transform:translateY(-2px)}
.qcard:active{transform:scale(.98)}
.qcard .qic{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;flex:none;
  background:var(--fill);color:var(--accent)}
.qcard b{display:block;font-size:13.5px;letter-spacing:-.01em}
.qcard small{display:block;font-size:11px;color:var(--ink-3);margin-top:2px;line-height:1.5}
.qcard.primary{background:var(--accent);border-color:transparent;color:var(--accent-ink)}
.qcard.primary .qic{background:color-mix(in srgb,var(--accent-ink) 18%,transparent);color:var(--accent-ink)}
.qcard.primary small{color:color-mix(in srgb,var(--accent-ink) 78%,transparent)}
.qcard.danger{background:var(--led-err);border-color:transparent;color:#fff}
.qcard.danger .qic{background:rgba(255,255,255,.2);color:#fff}
.qcard.danger small{color:rgba(255,255,255,.78)}
.qcard[disabled]{opacity:.45;pointer-events:none}

/* live sync card (compact lane + key stats + feed) */
#laneCard{padding:0;overflow:hidden;position:relative}
#laneWrap{position:relative;height:78px;background:
  radial-gradient(120% 150% at 50% -20%,color-mix(in srgb,var(--accent) 9%,transparent),transparent 60%)}
#lane{position:absolute;inset:0;width:100%;height:100%}
#laneInfo{position:absolute;left:14px;bottom:8px;right:14px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;
  font-size:11px;color:var(--ink-2);pointer-events:none}
#laneInfo b{font-family:var(--mono);color:var(--ink);font-variant-numeric:tabular-nums;font-weight:600}

.statstrip{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin:14px 0}
.statstrip .stat{background:var(--card);border:1px solid var(--line);border-radius:var(--r-md);padding:10px 13px;box-shadow:var(--shadow)}
.statstrip .k{font-size:11px;color:var(--ink-2)}
.statstrip .v{font-family:var(--mono);font-size:18px;font-weight:600;letter-spacing:-.02em;font-variant-numeric:tabular-nums;margin-top:2px}
.statstrip .v small{font-size:11px;color:var(--ink-3);font-weight:400}
.statstrip .stat.hot .v{color:var(--accent)}

#opsCard{padding:13px 16px}
#opsCard .oh{display:flex;align-items:center;gap:8px;margin-bottom:8px}
#opsCard .oh b{font-size:13px}
#opsCard .oh .mut{font-size:11px}
#opsList{max-height:150px;overflow:auto;display:flex;flex-direction:column;gap:2px}
.oprow{display:flex;align-items:center;gap:9px;padding:5px 2px;border-bottom:1px solid var(--line-2);font-size:12px;animation:pageIn .3s var(--ease)}
.oprow:last-child{border-bottom:0}
.oprow .ts{font-family:var(--mono);flex:none;font-size:11px;color:var(--ink-3)}
.oprow .src{flex:none;color:var(--accent);font-weight:600}
.oprow .path{font-family:var(--mono);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.oprow .path .v{color:var(--ink-2);font-variant-numeric:tabular-nums}
.oprow .dst{flex:none;color:var(--ink-2)}

/* log console */
#logbox{background:var(--console-bg);border-radius:var(--r-md);border:1px solid var(--line);
  font-family:var(--mono);font-size:11.5px;line-height:1.7;height:calc(100vh - 260px);min-height:280px;
  overflow:auto;padding:12px 14px;color:var(--console-ink)}
#logbox .t{color:var(--console-ink-2);margin-right:8px}
#logbox .INFO{color:#7ee2b8}#logbox .WARN{color:#ffd60a}#logbox .ERRO,#logbox .CRIT{color:#ff6961}#logbox .DEBU{color:var(--console-ink-2)}
#logbox div{white-space:pre-wrap;word-break:break-all;animation:logIn .25s var(--ease)}
@keyframes logIn{from{opacity:0;transform:translateX(-4px)}to{opacity:1;transform:none}}
.chips{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}
.chip{padding:3px 11px;border-radius:99px;font-size:12px;background:var(--fill);color:var(--ink-2);transition:all .15s}
.chip.sel{background:var(--accent);color:var(--accent-ink);font-weight:600}

/* docs */
.doc h4{font-size:13px;margin:14px 0 6px;display:flex;align-items:center;gap:7px}
.doc h4:first-child{margin-top:0}
.doc p{color:var(--ink-2);margin-bottom:6px}
.doc .warnbox{background:color-mix(in srgb,var(--led-warn) 12%,transparent);border:1px solid color-mix(in srgb,var(--led-warn) 35%,transparent);
  border-radius:var(--r-md);padding:10px 12px;font-size:12.5px;color:var(--ink);margin-bottom:12px}

/* sheet modal */
#sheetBg{position:fixed;inset:0;background:rgba(0,0,0,.28);backdrop-filter:blur(2px);opacity:0;pointer-events:none;
  transition:opacity .3s var(--ease);z-index:50;display:grid;place-items:start center;padding-top:12vh}
#sheetBg.on{opacity:1;pointer-events:auto}
#sheet{width:min(460px,86vw);background:var(--mat-strong);-webkit-backdrop-filter:blur(40px) saturate(1.8);backdrop-filter:blur(40px) saturate(1.8);
  border:1px solid var(--line);border-radius:16px;box-shadow:0 24px 80px rgba(0,0,0,.35);padding:22px;
  transform:translateY(-14px) scale(.98);opacity:0;transition:all .34s var(--ease);text-align:center}
#sheetBg.on #sheet{transform:none;opacity:1}
#sheet .ic{width:44px;height:44px;border-radius:50%;margin:0 auto 12px;display:grid;place-items:center;
  background:var(--fill);color:var(--accent)}
#sheet h3{font-size:15px;font-weight:700;margin-bottom:6px}
#sheet p{font-size:12.5px;color:var(--ink-2);margin-bottom:16px;line-height:1.6}
#sheet .acts{display:flex;gap:10px;justify-content:center}

/* popover (accent / theme) */
#pop{position:fixed;background:var(--mat-strong);-webkit-backdrop-filter:blur(36px) saturate(1.8);backdrop-filter:blur(36px) saturate(1.8);
  border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow);padding:10px;z-index:60;
  opacity:0;pointer-events:none;transform:scale(.94) translateY(-4px);transform-origin:top right;
  transition:all .22s var(--ease)}
#pop.on{opacity:1;pointer-events:auto;transform:none}
#pop .ttl{font-size:11px;color:var(--ink-2);font-weight:600;margin:2px 4px 7px}
.swatches{display:grid;grid-template-columns:repeat(4,26px);gap:8px;margin-bottom:10px}
.swatches button{width:26px;height:26px;border-radius:50%;box-shadow:inset 0 0 0 1px rgba(0,0,0,.12);transition:transform .15s var(--ease)}
.swatches button:hover{transform:scale(1.12)}
.swatches button.sel{box-shadow:0 0 0 2.5px var(--card),0 0 0 4.5px currentColor}

/* toast */
#toast{position:fixed;left:50%;bottom:26px;transform:translate(-50%,16px);background:var(--mat-strong);
  -webkit-backdrop-filter:blur(30px);backdrop-filter:blur(30px);border:1px solid var(--line);border-radius:12px;
  box-shadow:var(--shadow);padding:9px 16px;font-size:12.5px;display:flex;align-items:center;gap:8px;
  opacity:0;pointer-events:none;transition:all .3s var(--ease);z-index:70}
#toast.on{opacity:1;transform:translate(-50%,0)}

/* toolbar icon buttons */
.iconbtn{width:30px;height:30px;border-radius:8px;display:grid;place-items:center;color:var(--ink-2);transition:all .15s}
.iconbtn:hover{background:var(--fill);color:var(--ink)}

.mono{font-family:var(--mono)}
.mut{color:var(--ink-2)}
.tnum{font-variant-numeric:tabular-nums}
/* clearly visible scrollbars - the workspace scrolls inside #content */
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:color-mix(in srgb,var(--ink-3) 60%,transparent);border-radius:5px;border:2px solid transparent;background-clip:content-box}
::-webkit-scrollbar-thumb:hover{background:color-mix(in srgb,var(--ink-2) 80%,transparent);background-clip:content-box}
</style>
</head>
<body>
<div id="wall"></div>
<div id="app">

  <!-- ============ sidebar ============ -->
  <aside id="side">
    <div id="lights">
      <button class="l-close" title="关闭" data-act="close"><svg viewBox="0 0 12 12"><path d="M3.5 3.5l5 5M8.5 3.5l-5 5" stroke="#7a0d06" stroke-width="1.2" stroke-linecap="round"/></svg></button>
      <button class="l-min" title="最小化" data-act="min"><svg viewBox="0 0 12 12"><path d="M3 6h6" stroke="#7a5106" stroke-width="1.2" stroke-linecap="round"/></svg></button>
      <button class="l-max" title="全屏" data-act="max"><svg viewBox="0 0 12 12"><path d="M4 4h4v4" stroke="#0a5c12" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
    <div id="brand">
      <span class="logo"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M3 12h3l2-6 3 12 2.5-8 1.8 4H21"/></svg></span>
      x32-mirror
    </div>
    <nav id="nav">
      <button data-p="home" class="sel"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="8" height="7" rx="1.8"/><rect x="13" y="4" width="8" height="7" rx="1.8"/><rect x="3" y="13" width="8" height="7" rx="1.8"/><rect x="13" y="13" width="8" height="7" rx="1.8"/></svg>工作台</button>
      <button data-p="config"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2.2"/><circle cx="10" cy="17" r="2.2"/></svg>连接</button>
      <button data-p="ha"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v5c0 4.6-3 8.4-7 10-4-1.6-7-5.4-7-10V6z"/><path d="M9 12l2 2 4-4"/></svg>热备</button>
      <button data-p="backup"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M7 9v6M12 9v6M17 9v6"/></svg>备份</button>
      <button data-p="logs"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/></svg>日志</button>
      <button data-p="help"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M9.2 9.2a2.8 2.8 0 015.4 1c0 1.9-2.6 2.3-2.6 4"/><path d="M12 17.2h.01"/></svg>帮助</button>
    </nav>
    <div class="spacer"></div>
    <div id="enginePill"><span class="led off" id="pillLed"></span><span id="pillText">引擎未运行</span></div>
  </aside>

  <!-- ============ main ============ -->
  <main id="main">
    <div id="bar">
      <h1 id="pageTitle">工作台 <small id="pageSub"></small></h1>
      <button class="iconbtn" id="themeBtn" title="切换亮/暗色">
        <svg id="iconSun" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4"/></svg>
        <svg id="iconMoon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" style="display:none"><path d="M20 14.5A8.5 8.5 0 019.5 4 8.5 8.5 0 1020 14.5z"/></svg>
      </button>
      <button class="iconbtn" id="accentBtn" title="强调色">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><circle cx="9" cy="9.5" r="1.4" fill="currentColor" stroke="none"/><circle cx="15" cy="9.5" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="15" r="1.4" fill="currentColor" stroke="none"/></svg>
      </button>
      <span id="barActions" style="display:flex;gap:8px"></span>
    </div>

    <div id="content">

      <!-- ===== 工作台：卡片式选择 + 快捷操作 ===== -->
      <section class="page on" id="p-home">

        <!-- 01 调音台 -->
        <div class="sect">
          <div class="sh"><span class="n">01</span><span class="t">调音台</span>
            <span class="s">在线状态与地址</span>
            <span class="acts"><span class="badge" id="connBadge">未连接</span></span>
          </div>
          <div class="congrid">
            <div class="concard off" id="homeCardA">
              <div class="head"><span class="led big off" id="hLedA"></span><span class="nm">A</span>
                <span class="badge" id="hStateA">无数据</span></div>
              <div class="info mono" id="hInfoA">—</div>
              <div class="addr"><span>IP</span><input class="field mono" id="hIpA" placeholder="192.168.0.13"><span>端口</span><input class="field mono sm" id="hPortA" inputmode="numeric"></div>
              <div class="meters">
                <div class="meter"><span>最后消息</span><div class="track"><div class="fill" id="hAgeFillA" style="width:0"></div></div><b id="hAgeA">—</b></div>
                <div class="meter"><span>链路</span><div class="track"><div class="fill" id="hLinkFillA" style="width:0"></div></div><b id="hLinkA">—</b></div>
              </div>
            </div>
            <div class="concard off" id="homeCardB">
              <div class="head"><span class="led big off" id="hLedB"></span><span class="nm">B</span>
                <span class="badge" id="hStateB">无数据</span></div>
              <div class="info mono" id="hInfoB">—</div>
              <div class="addr"><span>IP</span><input class="field mono" id="hIpB" placeholder="192.168.0.31"><span>端口</span><input class="field mono sm" id="hPortB" inputmode="numeric"></div>
              <div class="meters">
                <div class="meter"><span>最后消息</span><div class="track"><div class="fill" id="hAgeFillB" style="width:0"></div></div><b id="hAgeB">—</b></div>
                <div class="meter"><span>链路</span><div class="track"><div class="fill" id="hLinkFillB" style="width:0"></div></div><b id="hLinkB">—</b></div>
              </div>
            </div>
          </div>
        </div>

        <!-- 02 同步模式 -->
        <div class="sect">
          <div class="sh"><span class="n">02</span><span class="t">同步模式</span><span class="s">主机</span>
            <span class="acts">
              <div class="seg" id="masterSeg">
                <button data-v="a" class="sel">以 A 为主</button><button data-v="b">以 B 为主</button>
              </div>
            </span>
          </div>
          <div class="modes" id="modeCards">
            <button class="modecard" data-m="single">
              <span class="glyph">A → B</span><b>单控台</b>
              <small>主台操作，备台跟随。备台误操作后自动回弹。</small>
            </button>
            <button class="modecard" data-m="mirror">
              <span class="glyph">A ⇄ B</span><b>双控台全镜像</b>
              <small>双侧双向同步，支持的屏幕状态一起跟随。</small>
            </button>
            <button class="modecard" data-m="independent">
              <span class="glyph">A · B</span><b>双控台显示独立</b>
              <small>双侧双向同步，两边屏幕各自操作。</small>
            </button>
          </div>
          <p class="modenote">切换前会先做<b>安全检测</b>：以<b>主机</b>为基准预检兼容参数、写入备台并逐项读回核对（不一致会自动恢复一次），期间请勿操作调音台。单控台模式下备台误操作约 <b>0.5 秒</b>后自动回弹到主机状态；两台同时操作时以主机为准。未连接时修改模式，将在下次启动镜像后生效。</p>
        </div>

        <!-- 03 运行状态：可以操作调音台 + 链路核对计数 -->
        <div class="sect" id="runSect" style="display:none">
          <div class="sh"><span class="n">03</span><span class="t">运行状态</span>
            <span class="s">显示“可以操作调音台”时才做现场操作</span>
          </div>
          <div class="runcard" id="runCard">
            <div class="rc-top">
              <div>
                <div class="rc-t"><span class="led on" id="rcLed"></span><span id="rcTitle">镜像运行中</span></div>
                <div class="rc-sub" id="rcSub">—</div>
              </div>
              <div class="rc-acts">
                <button class="btn" id="rcPause">暂停同步</button>
                <button class="btn danger" id="rcStop">结束同步</button>
              </div>
            </div>
            <div class="rc-bot">
              <div class="rc-stats" id="rcStats"></div>
              <button class="btn plain" id="rcLogs" style="margin-left:auto">查看日志 →</button>
            </div>
          </div>
        </div>

        <!-- 04 快捷操作 -->
        <div class="sect">
          <div class="sh"><span class="n">04</span><span class="t">快捷操作</span></div>
          <div class="quick" id="quickRow"></div>
        </div>

        <!-- 05 实时同步（运行中显示） -->
        <div class="sect" id="liveSect" style="display:none">
          <div class="sh"><span class="n">05</span><span class="t">实时同步</span>
            <span class="s">界面仅展示同步过程，不写台</span>
            <span class="acts" id="opsPending"></span>
          </div>
          <div class="card" id="laneCard">
            <div id="laneWrap"><canvas id="lane"></canvas></div>
            <div id="laneInfo">
              <span>同步模式 · <b id="laneMode">—</b><b id="laneDir" style="margin-left:8px"></b><b id="laneDelay" style="margin-left:8px;color:var(--led-warn)"></b></span>
              <span>回声抑制 <b id="laneEcho">0</b> · 合并写入 <b id="laneCoal">0</b> · 对账修复 <b id="laneRec">0</b></span>
              <span>实测延迟 <b id="laneLat">—</b></span>
            </div>
          </div>
          <div class="statstrip" id="statStrip"></div>
          <div class="card" id="opsCard">
            <div class="oh"><b>最近同步操作</b><span class="mut">界面仅展示，不写台</span></div>
            <div id="opsList"></div>
          </div>
        </div>

      </section>

      <!-- ===== 连接配置 ===== -->
      <section class="page" id="p-config">
        <div class="group">
          <div class="gh">调音台 A（主参考源）</div>
          <div class="row"><span class="lab">IP 地址</span><span class="val"><input class="field mono" id="aHost" placeholder="192.168.1.100"></span></div>
          <div class="row"><span class="lab">端口</span><span class="val"><input class="field mono" id="aPort" style="max-width:110px" inputmode="numeric"></span></div>
          <div class="row"><span class="lab">型号驱动<small>auto 自动探测</small></span><span class="val">
            <select class="field" id="aDrv" style="max-width:130px"></select>
            <button class="btn" id="aDetect">检测</button></span></div>
        </div>
        <div class="group">
          <div class="gh">调音台 B（镜像目标）</div>
          <div class="row"><span class="lab">IP 地址</span><span class="val"><input class="field mono" id="bHost" placeholder="192.168.1.101"></span></div>
          <div class="row"><span class="lab">端口</span><span class="val"><input class="field mono" id="bPort" style="max-width:110px" inputmode="numeric"></span></div>
          <div class="row"><span class="lab">型号驱动</span><span class="val">
            <select class="field" id="bDrv" style="max-width:130px"></select>
            <button class="btn" id="bDetect">检测</button></span></div>
        </div>
        <div class="group">
          <div class="gh">同步选项</div>
          <div class="row"><span class="lab">监听端口<small>遥控软件连接本工具的端口</small></span><span class="val"><input class="field mono" id="listenPort" style="max-width:110px" inputmode="numeric"></span></div>
          <div class="row"><span class="lab">同步方向</span><span class="val">
            <div class="seg" id="dirSeg">
              <button data-v="both" class="sel">双向</button><button data-v="a_to_b">A → B</button><button data-v="b_to_a">B → A</button>
            </div></span></div>
          <div class="row"><span class="lab">同步延迟<small>A 操作后延迟多少秒再同步到 B</small></span><span class="val">
            <input class="field mono" id="syncDelay" style="max-width:110px" inputmode="decimal" placeholder="0">
            <span class="mut" style="font-size:11px">秒 · 0 = 实时同步</span></span></div>
          <div class="row"><span class="lab">启动时安全检测<small>先预检并读回核对，再进入实时同步</small></span><span class="val"><label class="sw"><input type="checkbox" id="fullSync"><i></i></label></span></div>
          <div class="row note" style="justify-content:flex-end"><span>修改后点右上角「存储」生效（重启镜像后完全生效）</span></div>
        </div>
      </section>

      <!-- ===== 双机热备 ===== -->
      <section class="page" id="p-ha">
        <div class="grid g2">
          <div>
            <div class="group">
              <div class="gh">双机热备（HA）</div>
              <div class="row"><span class="lab">启用双机热备<small>两台电脑互为主备</small></span><span class="val"><label class="sw"><input type="checkbox" id="haEnable"><i></i></label></span></div>
              <div class="row"><span class="lab">本机节点名</span><span class="val"><input class="field mono" id="haNode" placeholder="pc-1" style="max-width:150px"></span></div>
              <div class="row"><span class="lab">对端地址</span><span class="val"><input class="field mono" id="haPeer" placeholder="192.168.1.50" style="max-width:150px"></span></div>
              <div class="row"><span class="lab">心跳端口</span><span class="val"><input class="field mono" id="haPort" style="max-width:110px" inputmode="numeric"></span></div>
              <div class="row"><span class="lab">故障切换<small>对端失联多少秒后接管</small></span><span class="val"><input class="field mono" id="haFailover" style="max-width:110px" inputmode="numeric"></span></div>
              <div class="row"><span class="lab">自动恢复<small>让位后对端宕机时重新接管</small></span><span class="val"><input class="field mono" id="haResume" style="max-width:110px" inputmode="numeric"></span></div>
              <div class="row"><span class="lab">保存 HA 设置</span><span class="val"><button class="btn primary" id="haSave">存储</button></span></div>
            </div>
          </div>
          <div>
            <div class="card" style="margin-bottom:18px">
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
                <span class="led off" id="haLed"></span><b style="font-size:14px">本机角色</b>
                <span class="badge" id="haRoleBadge" style="margin-left:auto">—</span>
              </div>
              <div class="row" style="padding:6px 0;border:0"><span class="lab mut">节点</span><span class="val mono" id="haNodeId">—</span></div>
              <div class="row" style="padding:6px 0;border:0"><span class="lab mut">Epoch</span><span class="val mono tnum" id="haEpoch">0</span></div>
              <div class="row" style="padding:6px 0;border:0"><span class="lab mut">对端</span><span class="val mono" id="haPeerInfo">—</span></div>
              <div style="font-size:11.5px;color:var(--ink-3);line-height:1.7;margin-top:8px">
                先启动的电脑自动成为主机负责同步；主机宕机 3 秒内备机自动接管。<br>
                手动切换会立即改变主备，重启后回到自动选举规则。
              </div>
            </div>
            <div style="display:flex;gap:10px">
              <button class="btn primary big" id="haPromote" style="flex:1">⇧ 升为主机</button>
              <button class="btn big" id="haDemote" style="flex:1">⇩ 让为备机</button>
            </div>
          </div>
        </div>
      </section>

      <!-- ===== 备份恢复 ===== -->
      <section class="page" id="p-backup">
        <div class="group">
          <div class="gh">本地快照</div>
          <div class="row"><span class="lab">立即拍摄<small>读取 A 台当前全部状态</small></span><span class="val"><button class="btn primary" id="btnSnap">📸 拍摄快照</button></span></div>
          <div class="row note" id="snapMsg" style="justify-content:flex-end"></div>
        </div>
        <div class="group">
          <div class="gh">恢复（写回两台调音台）</div>
          <div class="row" style="border-top:0"><span class="lab mut" style="flex:1">快照列表</span></div>
          <div id="snapList"></div>
        </div>
        <div class="group">
          <div class="gh">云备份（可选）</div>
          <div class="row"><span class="lab">启用云备份<small>镜像留局域网，快照上云</small></span><span class="val"><label class="sw"><input type="checkbox" id="cloudEnable"><i></i></label></span></div>
          <div class="row"><span class="lab">服务商</span><span class="val"><select class="field" id="cloudProvider" style="max-width:150px"><option value="s3">S3 兼容</option><option value="webdav">WebDAV</option><option value="local">本地目录</option></select></span></div>
          <div class="row"><span class="lab">Endpoint</span><span class="val"><input class="field mono" id="cloudEndpoint" placeholder="https://s3.amazonaws.com"></span></div>
          <div class="row"><span class="lab">存储桶 / 目录</span><span class="val"><input class="field mono" id="cloudBucket"></span></div>
          <div class="row"><span class="lab">Access Key</span><span class="val"><input class="field mono" id="cloudAk"></span></div>
          <div class="row"><span class="lab">Secret Key</span><span class="val"><input class="field mono" id="cloudSk" type="password"></span></div>
          <div class="row"><span class="lab">上传间隔<small>小时</small></span><span class="val"><input class="field mono" id="cloudHours" style="max-width:110px" inputmode="numeric"></span></div>
          <div class="row"><span class="lab">保存云设置</span><span class="val"><button class="btn primary" id="cloudSave">存储</button></span></div>
        </div>
      </section>

      <!-- ===== 实时日志 ===== -->
      <section class="page" id="p-logs">
        <div class="chips" id="logChips">
          <button class="chip sel" data-lv="all">全部</button>
          <button class="chip" data-lv="INFO">信息</button>
          <button class="chip" data-lv="WARN">警告</button>
          <button class="chip" data-lv="ERRO">错误</button>
          <button class="chip" id="logClear" style="margin-left:auto">清屏</button>
        </div>
        <div id="logbox"></div>
      </section>

      <!-- ===== 使用说明 ===== -->
      <section class="page" id="p-help">
        <div class="card doc" id="docBox"></div>
      </section>

    </div>
  </main>
</div>

<!-- safety-check progress dialog (mode switch / start) -->
<div id="jobBg"><div id="jobDlg">
  <h3 id="jobTitle">模式切换安全检测</h3>
  <p id="jobDesc">正在以 A 台为基准对齐 B 台，并读回核对允许同步的参数。请暂勿操作两台调音台或 All Live，完成会提示可以操作。</p>
  <div class="jtarget" id="jobTarget">正在切换…</div>
  <div class="pbar"><i id="jobBar"></i></div>
  <div class="jline" id="jobLine">Node写入 0/0 · 错误 0 · —</div>
  <div class="jdone" id="jobDone"></div>
  <div class="jnote">取消会停止本次处理；已经写入的参数不会自动撤销。</div>
  <div class="jacts"><button class="btn big" id="jobCancel">取消</button></div>
</div></div>

<!-- sheet + popover + toast -->
<div id="sheetBg"><div id="sheet">
  <div class="ic" id="sheetIc"></div><h3 id="sheetTitle"></h3><p id="sheetBody"></p>
  <div class="acts" id="sheetActs"></div>
</div></div>
<div id="pop">
  <div class="ttl">强调色</div>
  <div class="swatches" id="swatches"></div>
  <div class="ttl">外观</div>
  <div class="seg" id="themeSeg" style="width:100%">
    <button data-t="auto" class="sel" style="flex:1">自动</button><button data-t="light" style="flex:1">浅色</button><button data-t="dark" style="flex:1">深色</button>
  </div>
</div>
<div id="toast"></div>

<script>
"use strict";
const $=id=>document.getElementById(id);
const API={
  get:async u=>(await fetch(u)).json(),
  post:async(u,d)=>{const r=await fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d||{})});return r.json()}
};
const ACCENTS={blue:"#0a84ff",purple:"#bf5af2",pink:"#ff375f",red:"#ff453a",orange:"#ff9f0a",yellow:"#e0b400",green:"#30d158",graphite:"#8e8e93"};
const ACCENT_INK={yellow:"#3a2f00",graphite:"#fff"};
let state={page:"home",theme:"auto",accent:"blue",running:false,status:null,ha:null,mode:null,prev:null,latHist:[],dots:[],logSeq:0,logLv:"all",logBuf:[],docs:null,cfgLoaded:false};
const MODE_LABEL={single:"单控台",mirror:"双控台全镜像",independent:"双控台显示独立"};
const PHASE_LABEL={preflight:"兼容预检",scan:"读取主机状态",align:"写入备台",verify:"读回核对",done:"已完成",cancelled:"已取消",failed:"检测失败"};
let jobTimer=null,jobOpen=false;

/* ---------------- theme / accent ---------------- */
function applyTheme(){
  const t=state.theme;
  if(t==="auto")document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme",t);
  const dark=t==="dark"||(t==="auto"&&matchMedia("(prefers-color-scheme:dark)").matches);
  $("iconSun").style.display=dark?"none":"block";
  $("iconMoon").style.display=dark?"block":"none";
}
function applyAccent(){
  const c=ACCENTS[state.accent];
  document.documentElement.style.setProperty("--accent",c);
  document.documentElement.style.setProperty("--accent-ink",ACCENT_INK[state.accent]||"#fff");
  document.querySelectorAll("#swatches button").forEach(b=>b.classList.toggle("sel",b.dataset.c===state.accent));
}
$("themeBtn").onclick=()=>{state.theme=state.theme==="auto"?(matchMedia("(prefers-color-scheme:dark)").matches?"light":"dark"):state.theme;applyTheme()};
$("accentBtn").onclick=e=>{const p=$("pop");const r=$("accentBtn").getBoundingClientRect();
  p.style.top=(r.bottom+6)+"px";p.style.right=(innerWidth-r.right)+"px";p.classList.toggle("on");e.stopPropagation()};
document.addEventListener("click",e=>{if(!$("pop").contains(e.target)&&e.target!==$("accentBtn"))$("pop").classList.remove("on")});
$("swatches").innerHTML=Object.entries(ACCENTS).map(([k,v])=>`<button data-c="${k}" style="background:${v};color:${v}"></button>`).join("");
$("swatches").onclick=e=>{const b=e.target.closest("button");if(!b)return;state.accent=b.dataset.c;applyAccent()};
$("themeSeg").onclick=e=>{const b=e.target.closest("button");if(!b)return;
  $("themeSeg").querySelectorAll("button").forEach(x=>x.classList.toggle("sel",x===b));state.theme=b.dataset.t;applyTheme()};
matchMedia("(prefers-color-scheme:dark)").addEventListener("change",applyTheme);

/* ---------------- nav ---------------- */
const TITLES={home:["工作台",""],config:["连接","调音台地址与同步选项"],ha:["热备","主备选举与手动切换"],backup:["备份","快照与云备份"],logs:["日志","引擎运行日志"],help:["帮助","操作指南与注意事项"]};
function goto(p){
  state.page=p;
  document.querySelectorAll("nav button").forEach(b=>b.classList.toggle("sel",b.dataset.p===p));
  document.querySelectorAll(".page").forEach(s=>s.classList.toggle("on",s.id==="p-"+p));
  $("pageTitle").firstChild.textContent=TITLES[p][0]+" ";
  $("pageSub").textContent=p==="home"?"":TITLES[p][1];
  renderBar();
  if(p==="logs")pollLogs(true);
  if(p==="config")loadConfig();
  if(p==="backup")loadSnaps();
  if(p==="ha")loadHA();
  if(p==="help")loadDocs();
  if(p==="home")renderHome();
}
$("nav").onclick=e=>{const b=e.target.closest("button");if(b)goto(b.dataset.p)};
function renderBar(){
  const a=$("barActions");a.innerHTML="";
  if(state.page==="config"){
    const b=document.createElement("button");b.className="btn primary big";b.textContent="存储";
    b.onclick=saveConfig;a.appendChild(b);
  }
  if(state.page==="ha"){
    const b=document.createElement("button");b.className="btn big";b.textContent="刷新状态";
    b.onclick=()=>{poll(true)};a.appendChild(b);
  }
  if(state.page==="home"){
    // the workspace keeps the primary action in the quick-action row;
    // the bar only mirrors it while other pages are open
    if(state.running){
      const b=document.createElement("button");b.className="btn danger big";b.id="btnStop";
      b.innerHTML='<svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>停止镜像';
      b.onclick=stopEngine;a.appendChild(b);
    }else{
      const b=document.createElement("button");b.className="btn primary big";b.id="btnStart";
      b.innerHTML='<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l13-7.5z"/></svg>启动镜像';
      b.onclick=startEngine;a.appendChild(b);
    }
  }
}

/* ---------------- workspace (home) ---------------- */
function fmtAge(a){return a==null?"无数据":(a<3?"● 在线":(a<15?"● 迟缓":"○ 失联"))}
function ledClass(c){return c.alert||!c.online?(c.online?"warn":"err"):(c.last_seen_age_s!=null&&c.last_seen_age_s<3?"on":"off")}
function renderPill(s){
  const pl=$("pillLed"),pt=$("pillText");
  if(!s){pl.className="led off";pt.textContent="引擎未运行";}
  else if(!s.running){pl.className="led off";pt.textContent=s.error?"引擎启动出错":"引擎未运行";}
  else{pl.className="led "+(s.active?"on":"warn");pt.textContent=(s.role||"")+(s.active?" · 转发中":" · 只记录");}
}
function fmtNum(n){return (n||0).toLocaleString("en-US")}
/* 03 run status card: title says whether the operator may touch the desks,
   the bottom row carries the link counters (forward / read-back / pending). */
function renderRunCard(s){
  const st=s.stats||{}, jb=s.sync_job||{}, la=s.last_align||null;
  const busy=!!jb.active;
  $("rcLed").className="led "+(busy?"warn":(s.paused?"off":"on"));
  let title,sub;
  if(busy){
    title=`安全检测中 · ${jb.pct||0}%`;
    sub=`${PHASE_LABEL[jb.phase]||jb.phase} · Node ${jb.written||0}/${jb.total||0} · 请勿操作调音台`;
  }else if(s.paused){
    title="已暂停同步 · 调音台各自独立";
    sub="链路保持，转发已停止";
  }else{
    const ml=MODE_LABEL[s.sync_mode]||s.sync_mode||"镜像";
    title=`${ml}模式 · 可以操作调音台`;
    const n=(la&&la.intersection)||s.sync_paths||0;
    sub=(la&&la.ok===false&&la.pending)
      ?`兼容预检通过 · 安全交集 ${fmtNum(n)} 项 · ${la.pending} 项待核对`
      :`兼容预检通过 · 安全交集 ${fmtNum(n)} 项`;
  }
  $("rcTitle").textContent=title;
  $("rcSub").textContent=sub;
  $("runCard").classList.toggle("paused",!!s.paused);
  const pb=$("rcPause");pb.textContent=s.paused?"继续同步":"暂停同步";pb.disabled=busy;
  const rows=[["转发",st.forwarded||0,"hot"],["读回确认",st.readback_ok||0,""],
              ["待核对",st.readback_pending||0,(st.readback_pending||0)>0?"bad":""],
              ["自动恢复",st.auto_restored||0,""]];
  $("rcStats").innerHTML=rows.map(([k,v,c])=>`<span class="${c}">${k}<b>${v}</b></span>`).join("");
}
function renderHome(){
  const s=state.status;
  renderPill(s);
  $("liveSect").style.display=state.running?"block":"none";

  // ---- 03 run status: "可以操作调音台" + link counters ----
  $("runSect").style.display=(state.running&&s)?"block":"none";
  if(state.running&&s)renderRunCard(s);

  // ---- console cards ----
  const badge=$("connBadge");
  badge.textContent=state.running?"连接成功":"未连接";
  badge.className="badge "+(state.running?"ok":"");
  const cons=(s&&s.consoles)||[];
  const xi=(s&&s.xinfo)||{};
  const drv=(s&&s.drivers)||[];
  [["A","hLedA","hStateA","hInfoA","hIpA","hPortA","hAgeFillA","hAgeA","hLinkFillA","hLinkA",0,"a","homeCardA"],
   ["B","hLedB","hStateB","hInfoB","hIpB","hPortB","hAgeFillB","hAgeB","hLinkFillB","hLinkB",1,"b","homeCardB"]]
   .forEach(([tag,led,st,info,ip,port,af,av,lf,lv,i,xk,card])=>{
    const c=cons[i];
    const on=!!(c&&c.online);
    $(led).className="led big "+(on?"on":(c&&c.alert?"err":"off"));
    $(st).textContent=on?"在线":(c&&c.age_s!=null?"失联":"无数据");
    $(st).className="badge "+(on?"ok":(c&&c.alert?"err":""));
    const args=xi&&xi[xk];
    $(info).textContent=(args&&args.length?args.join(" · "):"—")+(drv[i]?("  ["+drv[i]+"]"):"");
    if(document.activeElement!==$(ip))$(ip).value=c?c.host:"";
    if(document.activeElement!==$(port))$(port).value=c?c.port:"";
    $(card).classList.toggle("off",!on&&!!c);
    const age=c?(c.last_seen_age_s!=null?c.last_seen_age_s:c.age_s):null;
    $(af).style.width=age==null?0:Math.max(2,100-Math.min(100,age*7))+"%";
    $(av).textContent=age==null?"—":age+"s";
    $(lf).style.width=(c&&c.online)?100:((c&&c.alert)?25:0)+"%";
    $(lv).textContent=fmtAge(age);
  });

  // ---- mode cards + master seg ----
  const m=state.mode||{};
  $("masterSeg").querySelectorAll("button").forEach(x=>x.classList.toggle("sel",x.dataset.v===(m.master||"a")));
  document.querySelectorAll("#modeCards .modecard").forEach(x=>x.classList.toggle("sel",x.dataset.m===(m.sync_mode||"mirror")));

  // ---- quick action cards (rebuilt only when the run state flips, so a
  // click is never lost to a poll re-render) ----
  const q=$("quickRow");
  const snapDisabled=state.running?"":"disabled";
  if(state.quickKey!==state.running){
  state.quickKey=state.running;
  if(state.running){
    q.innerHTML=`
      <button class="qcard danger" id="qStop">
        <span class="qic"><svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg></span>
        <span><b>停止镜像</b><small>断开同步链路，两台各自运行</small></span></button>
      <button class="qcard" id="qSnap" ${snapDisabled}>
        <span class="qic"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8.5A2.5 2.5 0 016.5 6h1.2l1.1-1.8h6.4L16.3 6h1.2A2.5 2.5 0 0120 8.5v8A2.5 2.5 0 0117.5 19h-11A2.5 2.5 0 014 16.5z"/><circle cx="12" cy="12.5" r="3.4"/></svg></span>
        <span><b>拍摄快照</b><small>保存 A 台当前全部状态</small></span></button>
      <button class="qcard" id="qLogs">
        <span class="qic"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/></svg></span>
        <span><b>实时日志</b><small>查看引擎运行日志</small></span></button>`;
  }else{
    q.innerHTML=`
      <button class="qcard primary" id="qStart">
        <span class="qic"><svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l13-7.5z"/></svg></span>
        <span><b>启动镜像</b><small>先做安全检测与基线对齐，再实时互同步</small></span></button>
      <button class="qcard" id="qSnap" ${snapDisabled}>
        <span class="qic"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8.5A2.5 2.5 0 016.5 6h1.2l1.1-1.8h6.4L16.3 6h1.2A2.5 2.5 0 0120 8.5v8A2.5 2.5 0 0117.5 19h-11A2.5 2.5 0 014 16.5z"/><circle cx="12" cy="12.5" r="3.4"/></svg></span>
        <span><b>拍摄快照</b><small>需先启动镜像</small></span></button>
      <button class="qcard" id="qLogs">
        <span class="qic"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/></svg></span>
        <span><b>实时日志</b><small>查看引擎运行日志</small></span></button>`;
  }
  $("qStart")&&($("qStart").onclick=startEngine);
  $("qStop")&&($("qStop").onclick=stopEngine);
  $("qSnap")&&($("qSnap").onclick=async()=>{
    $("qSnap").disabled=true;
    const r=await API.post("/api/snapshot");
    toast(r.ok?`快照已保存：${r.file}（${r.paths} 个参数）`:"拍摄失败："+(r.error||""),r.ok?"ok":"err");
    $("qSnap").disabled=false;
  });
  $("qLogs")&&($("qLogs").onclick=()=>goto("logs"));
  }

  // ---- bar title carries the live mode summary ----
  if(state.running&&s){
    const ml=MODE_LABEL[s.sync_mode]||s.sync_mode||"—";
    const dir=s.direction==="both"?"A ⇄ B":(s.direction==="a_to_b"?"A → B":"B → A");
    const mast=s.sync_mode==="single"?(" · "+((s.master||"a").toUpperCase())+" 为主"):"";
    $("pageSub").textContent=ml+mast+" · "+dir+(s.latency_ms!=null?(" · "+s.latency_ms+" ms"):"");
  }else{
    $("pageSub").textContent="";
  }
  renderBar();

  if(!s||!s.running)return;

  // ---- live sync ----
  const st=s.stats||{};
  $("laneMode").textContent=(MODE_LABEL[s.sync_mode]||s.sync_mode||"—")+
    (s.sync_mode==="single"?(" · "+((s.master||"a").toUpperCase())+" 为主"):"");
  $("laneDir").textContent=s.direction==="both"?"A ⇄ B":(s.direction==="a_to_b"?"A → B":"B → A");
  $("laneDelay").textContent=s.sync_delay_s>0?("⏱ 延迟 "+s.sync_delay_s+"s"):"";
  $("laneEcho").textContent=st.echo_suppressed||0;
  $("laneCoal").textContent=st.coalesced||0;
  $("laneRec").textContent=st.reconciled||0;
  $("laneLat").textContent=s.latency_ms==null?"—":s.latency_ms+" ms";

  // live operation feed (display only - the UI never writes to consoles)
  const ops=(s.recent_ops||[]).slice(-7).reverse();
  $("opsPending").innerHTML=s.pending_delay?`<span class="badge warn">⏱ ${s.pending_delay} 个操作延迟同步中</span>`:
    (s.pending_revert?`<span class="badge warn">↩ ${s.pending_revert} 个误操作回弹中</span>`:"");
  $("opsList").innerHTML=ops.length?ops.map(o=>{
    const tag=o.state==="delayed"?`<span class="badge warn">延迟中</span>`
             :o.state==="reverting"?`<span class="badge warn">回弹中</span>`
             :o.state==="reverted"?`<span class="badge ok">已回弹</span>`
             :`<span class="badge ok">${o.delay?("延迟 "+o.delay+"s 已同步"):"已同步"}</span>`;
    return `<div class="oprow">
      <span class="ts">${o.ts}</span>
      <b class="src">${esc(o.src)}</b>
      <span class="path">${esc(o.path)} <span class="v">${o.val==null?"":esc(String(o.val))}</span></span>
      <span class="dst">→ ${esc(o.dst)}</span>
      ${tag}</div>`;
  }).join(""):'<div class="mut" style="font-size:12px;padding:10px 2px">暂无同步操作。在任意一台调音台上操作，这里会实时显示同步过程。</div>';

  // key numbers only — keep the workspace minimal
  const grid=[
    ["转发写入",st.forwarded||0,"","hot"],["回声抑制",st.echo_suppressed||0,"",""],
    ["收到事件",st.received||0,"",""],["误操作回弹",st.reverts||0,"次",""],
    ["实测延迟",s.latency_ms==null?"—":s.latency_ms,"ms",""],
  ];
  $("statStrip").innerHTML=grid.map(([k,v,u,hot])=>`<div class="stat ${hot}"><div class="k">${k}</div><div class="v">${v}<small> ${u}</small></div></div>`).join("");

  // feed the sync lane
  const p=state.prev||{};
  const dRecv=Math.max(0,(st.received||0)-(p.received||0));
  const dFwd=Math.max(0,(st.forwarded||0)-(p.forwarded||0));
  const dEcho=Math.max(0,(st.echo_suppressed||0)-(p.echo_suppressed||0));
  for(let i=0;i<Math.min(dRecv,26);i++)spawnDot("recv",i);
  for(let i=0;i<Math.min(dFwd,26);i++)spawnDot("fwd",i);
  for(let i=0;i<Math.min(dEcho,8);i++)spawnDot("echo",i);
  state.prev={received:st.received||0,forwarded:st.forwarded||0,echo_suppressed:st.echo_suppressed||0};
  if(s.latency_ms!=null){state.latHist.push(s.latency_ms);if(state.latHist.length>60)state.latHist.shift();}
}

/* sync lane visualizer */
const lane=$("lane"),lctx=lane.getContext("2d");
let laneT=0;
function spawnDot(kind,delay){
  const fromA=Math.random()<.5;
  state.dots.push({kind,fromA,delay:delay*14+Math.random()*10,
    y:26+Math.random()*36,speed:1.6+Math.random()*1.2,born:laneT});
  if(state.dots.length>240)state.dots.splice(0,60);
}
function drawLane(ts){
  if(!laneT)laneT=ts;
  const dt=Math.min(50,ts-laneT);laneT=ts;
  const w=lane.clientWidth,h=lane.clientHeight,dpr=devicePixelRatio||1;
  if(!w||!h){requestAnimationFrame(drawLane);return;}
  if(lane.width!==w*dpr){lane.width=w*dpr;lane.height=h*dpr;}
  lctx.setTransform(dpr,0,0,dpr,0,0);
  lctx.clearRect(0,0,w,h);
  const s=state.status;
  const onlineA=s&&s.consoles?s.consoles[0].online:false;
  const onlineB=s&&s.consoles?s.consoles[1].online:false;
  const ax=58,bx=w-58,cy=h/2;
  const css=getComputedStyle(document.documentElement);
  const accent=css.getPropertyValue("--accent").trim()||"#0a84ff";
  const ink3=css.getPropertyValue("--ink-3").trim()||"#999";
  const ledOn=css.getPropertyValue("--led-on").trim()||"#28cd41";

  // lane rail
  lctx.strokeStyle=ink3;lctx.globalAlpha=.35;lctx.lineWidth=1.5;
  lctx.beginPath();lctx.moveTo(ax,cy);lctx.lineTo(bx,cy);lctx.stroke();lctx.globalAlpha=1;

  // endpoints
  const drawNode=(x,label,on)=>{
    lctx.beginPath();lctx.arc(x,cy,15,0,7);
    lctx.fillStyle=on?ledOn:ink3;lctx.globalAlpha=on?.9:.35;lctx.fill();lctx.globalAlpha=1;
    lctx.fillStyle="#fff";lctx.font="700 10px "+getComputedStyle(document.body).fontFamily;
    lctx.textAlign="center";lctx.textBaseline="middle";lctx.fillText(label,x,cy+1);
  };
  drawNode(ax,"A",onlineA);drawNode(bx,"B",onlineB);

  // dots
  state.dots=state.dots.filter(d=>{
    d.delay-=dt;if(d.delay>0)return true;
    d.x=(d.fromA?ax:bx)+(d.fromA?1:-1)*((ts-d.born-d.delay)*0.32*d.speed);
    if(Math.abs(d.x-(d.fromA?bx:ax))<22)return false;
    const col=d.kind==="fwd"?accent:(d.kind==="echo"?ink3:"#fff");
    lctx.globalAlpha=d.kind==="echo"?.35:.95;
    lctx.fillStyle=col;
    lctx.beginPath();lctx.arc(d.x,d.y,d.kind==="fwd"?2.6:2,0,7);lctx.fill();
    if(d.kind==="fwd"){lctx.globalAlpha=.25;lctx.beginPath();lctx.arc(d.x,d.y,5.5,0,7);lctx.fill();}
    lctx.globalAlpha=1;
    return true;
  });

  // latency sparkline
  const hist=state.latHist;
  if(hist.length>1){
    const sw=80,sh=22,sx=w-sw-14,sy=10;
    lctx.strokeStyle=accent;lctx.lineWidth=1.4;lctx.beginPath();
    const mx=Math.max(...hist,10);
    hist.forEach((v,i)=>{
      const x=sx+(i/(hist.length-1))*sw, y=sy+sh-(v/mx)*sh;
      i?lctx.lineTo(x,y):lctx.moveTo(x,y);
    });
    lctx.stroke();
    lctx.fillStyle=accent;lctx.globalAlpha=.12;lctx.lineTo(sx+sw,sy+sh);lctx.lineTo(sx,sy+sh);lctx.fill();lctx.globalAlpha=1;
  }
  requestAnimationFrame(drawLane);
}
requestAnimationFrame(drawLane);

/* ---------------- engine control ---------------- */
async function startEngine(){
  const cfg=collectConfig();
  const r=await API.post("/api/start",cfg);
  if(!r.ok){toast("启动失败："+(r.error||"未知错误"),"err");return;}
  toast("镜像引擎已启动，正在做安全检测…");
  state.prev=null;state.latHist=[];poll(true);
}
async function stopEngine(){
  sheet("停止镜像","停止后两台调音台将各自独立运行，同步链路断开。确定停止？",[
    {t:"取消",cls:"btn"},{t:"停止",cls:"btn danger",fn:async()=>{
      await API.post("/api/stop");toast("镜像已停止");poll(true);}}
  ],"stop");
}

/* ---------------- config page ---------------- */
let cfgCache=null;
async function loadConfig(){
  const d=await API.get("/api/config");cfgCache=d.config;
  const c=d.config;
  const sel=(el,v)=>{el.innerHTML=d.drivers.map(k=>`<option value="${k}" ${k===v?"selected":""}>${k}</option>`).join("")};
  sel($("aDrv"),c.consoles.a.driver||"auto");sel($("bDrv"),c.consoles.b.driver||"auto");
  $("aHost").value=c.consoles.a.host||"";$("aPort").value=c.consoles.a.port||10023;
  $("bHost").value=c.consoles.b.host||"";$("bPort").value=c.consoles.b.port||10023;
  $("listenPort").value=c.listen_port||10099;
  $("syncDelay").value=c.sync_delay_s||0;
  $("fullSync").checked=!!c.full_sync;
  $("dirSeg").querySelectorAll("button").forEach(b=>b.classList.toggle("sel",b.dataset.v===(c.direction||"both")));
  state.cfgLoaded=true;
}
function collectConfig(){
  // fall back to the cached config so the start button works even when the
  // config page was never visited (its inputs would still be empty)
  const c=cfgCache||{consoles:{a:{},b:{}}};
  const a=(c.consoles&&c.consoles.a)||{}, b=(c.consoles&&c.consoles.b)||{};
  const host=(id,fb)=>$(id).value.trim()||fb||"";
  const segSel=id=>{const s=$(id).querySelector(".sel");return s?s.dataset.v:null};
  return {consoles:{a:{host:host("aHost",a.host),port:+$("aPort").value||a.port||10023,driver:$("aDrv").value||a.driver||"auto"},
                   b:{host:host("bHost",b.host),port:+$("bPort").value||b.port||10023,driver:$("bDrv").value||b.driver||"auto"}},
          listen_port:+$("listenPort").value||c.listen_port||10099,
          direction:segSel("dirSeg")||c.direction||"both",
          sync_delay_s:Math.max(0,parseFloat($("syncDelay").value)||0),
          full_sync:(state.cfgLoaded?$("fullSync").checked:!!c.full_sync),
          sync_mode:(state.mode&&state.mode.sync_mode)||c.sync_mode||"mirror",
          master:(state.mode&&state.mode.master)||c.master||"a"};
}
$("dirSeg").onclick=e=>{const b=e.target.closest("button");if(!b)return;
  $("dirSeg").querySelectorAll("button").forEach(x=>x.classList.toggle("sel",x===b))};
async function saveConfig(){
  const r=await API.post("/api/config",collectConfig());
  toast(r.ok?"连接配置已存储":"保存失败："+(r.error||""),r.ok?"ok":"err");
}
$("aDetect").onclick=()=>detect("a");$("bDetect").onclick=()=>detect("b");
async function detect(side){
  const host=$(side+"Host").value.trim();
  if(!host){toast("请先填写 IP 地址","err");return;}
  toast("正在探测 "+host+" …");
  const d=await API.get("/api/detect?host="+encodeURIComponent(host));
  if(d.driver){$(side+"Drv").value=d.driver;toast(`识别到 ${d.model}，驱动已设为 ${d.driver}`);}
  else toast("未识别到调音台（"+host+"）","err");
}

/* ---------------- sync mode selection (cards) ---------------- */
async function loadMode(){
  try{
    state.mode=await API.get("/api/mode");
  }catch(e){}
}
function applyMode(mode,master){
  const cur=state.mode||{};
  if(mode===cur.sync_mode&&master===cur.master)return;
  const jb=state.status&&state.status.sync_job;
  if(jb&&jb.active){toast("安全检测进行中，请等待完成");return;}
  const apply=async()=>{
    const r=await API.post("/api/mode",{mode,master});
    if(!r.ok){toast("切换失败："+(r.error||""),"err");return;}
    state.mode=Object.assign({},cur,{sync_mode:mode,master:master,direction:r.direction});
    if(r.saved){toast("模式已保存，启动镜像后生效");return;}
    if(r.job&&r.job.active){
      openJob(r.job);  // safety check first: align + read-back, hands off
    }else if(r.realigned){
      toast("模式已切换，正在对齐主机状态…");
    }else{
      toast("模式已切换");
    }
    poll(true);
  };
  apply();
}
$("modeCards").onclick=e=>{const b=e.target.closest(".modecard");if(!b)return;
  applyMode(b.dataset.m,(state.mode||{}).master||"a")};
$("masterSeg").onclick=e=>{const b=e.target.closest("button");if(!b)return;
  applyMode((state.mode||{}).sync_mode||"mirror",b.dataset.v)};

/* console card IP/port inline edit (workspace) */
[["A","hIpA","hPortA"],["B","hIpB","hPortB"]].forEach(([tag,ip,port])=>{
  $(ip).onchange=async()=>{
    const side=tag.toLowerCase();
    const r=await API.post("/api/config",{consoles:{[side]:{host:$(ip).value.trim()}}});
    toast(r.ok?(`${tag} 台 IP 已保存（重启镜像后生效）`):"保存失败",r.ok?"ok":"err");
  };
  $(port).onchange=async()=>{
    const side=tag.toLowerCase();
    const r=await API.post("/api/config",{consoles:{[side]:{port:+$(port).value||10023}}});
    toast(r.ok?(`${tag} 台端口已保存（重启镜像后生效）`):"保存失败",r.ok?"ok":"err");
  };
});

/* ---------------- HA page ---------------- */
async function loadHA(){
  const d=await API.get("/api/config");const h=d.config.ha||{};
  $("haEnable").checked=!!h.enabled;$("haNode").value=h.node_id||"pc-1";
  $("haPeer").value=h.peer_host||"";$("haPort").value=h.port||49900;
  $("haFailover").value=h.failover_s||3;$("haResume").value=h.auto_resume_s||30;
}
$("haSave").onclick=async()=>{
  const r=await API.post("/api/config",{ha:{enabled:$("haEnable").checked,node_id:$("haNode").value.trim(),
    peer_host:$("haPeer").value.trim(),port:+$("haPort").value||49900,
    failover_s:+$("haFailover").value||3,auto_resume_s:+$("haResume").value||30}});
  toast(r.ok?"HA 设置已存储":"保存失败："+(r.error||""),r.ok?"ok":"err");
};
function renderHA(){
  const h=state.ha||{enabled:false};
  const on=!!h.enabled;
  $("haLed").className="led "+(on?(h.active?"on":"warn"):"off");
  $("haRoleBadge").textContent=on?(h.active?"主机 ACTIVE":"备机 STANDBY"):"未启用";
  $("haRoleBadge").style.background=on?"color-mix(in srgb, var(--led-on) 18%, transparent)":"var(--fill)";
  $("haNodeId").textContent=on?h.node_id:"—";
  $("haEpoch").textContent=on?h.epoch:0;
  const p=h.peer;
  $("haPeerInfo").innerHTML=on?((p?`${p.id} · ${p.active?"主机":"备机"} · ${p.epoch}`:"对端无应答")+
    ` <span class="mut">(${h.peer_host}:${h.port})</span>`):"—";
  $("haPromote").disabled=!on;$("haDemote").disabled=!on;
}
async function haSwitch(action){
  sheet(action==="promote"?"升为主机":"让为备机",
    action==="promote"?"本机将立即成为主机负责同步，对端转为备机。重启后回到自动选举。":
                        "本机将让位给对端成为备机（对端在线时仍只记录不转发）。",
    [{t:"取消",cls:"btn"},{t:action==="promote"?"确认升主":"确认让位",cls:"btn primary",fn:async()=>{
      const r=await API.post("/api/ha",{action});
      if(!r.ok){toast(r.error,"err");return;}
      toast(action==="promote"?"已升为主机":"已让为备机");poll(true);
    }}],action==="promote"?"arrow.up":"arrow.down");
}
$("haPromote").onclick=()=>haSwitch("promote");
$("haDemote").onclick=()=>haSwitch("demote");

/* ---------------- backup page ---------------- */
async function loadSnaps(){
  const d=await API.get("/api/snapshots");
  const files=d.files||[];
  $("snapList").innerHTML=files.length?files.slice(0,20).map(f=>
    `<div class="row"><span class="lab mono" style="flex:1">${f}</span><span class="val" style="flex:0 0 auto">
      <button class="btn" data-prev="${f}">预览</button>
      <button class="btn danger" data-res="${f}">写台</button></span></div>`).join(""):
    `<div class="row" style="border-top:0"><span class="mut" style="padding:14px 0">暂无快照。先在上方「立即拍摄」保存一个还原点。</span></div>`;
}
$("snapList").onclick=async e=>{
  const p=e.target.closest("[data-prev]"),r=e.target.closest("[data-res]");
  if(p){
    const d=await API.post("/api/restore",{file:p.dataset.prev,confirm:false});
    if(!d.ok){toast("预览失败："+(d.error||""),"err");return;}
    sheet("快照预览",`${d.file}<br>${d.ts} · ${d.model} · 共 <b>${d.paths}</b> 个参数（干跑，未写台）。`,[{t:"知道了",cls:"btn primary"}],"eye");
  }
  if(r){
    sheet("写回调音台",`将把快照 <b>${r.dataset.res}</b> 写回两台调音台，覆盖当前状态！`, [
      {t:"取消",cls:"btn"},{t:"确认写台",cls:"btn danger",fn:async()=>{
        const d=await API.post("/api/restore",{file:r.dataset.res,confirm:true});
        toast(d.ok?`恢复完成：${d.written} 个参数已写回`:"失败："+(d.error||""),d.ok?"ok":"err");
      }}],"exclamationmark.triangle");
  }
};
$("btnSnap").onclick=async()=>{
  $("btnSnap").disabled=true;$("snapMsg").textContent="正在读取调音台状态…";
  const r=await API.post("/api/snapshot");
  $("snapMsg").textContent=r.ok?`已保存 ${r.file}（${r.paths} 个参数）`:"失败："+(r.error||"");
  $("btnSnap").disabled=false;loadSnaps();
};
$("cloudSave").onclick=async()=>{
  const r=await API.post("/api/config",{cloud:{enabled:$("cloudEnable").checked,provider:$("cloudProvider").value,
    endpoint:$("cloudEndpoint").value.trim(),bucket:$("cloudBucket").value.trim(),
    access_key:$("cloudAk").value.trim(),secret_key:$("cloudSk").value.trim(),
    interval_hours:+$("cloudHours").value||6}});
  toast(r.ok?"云备份设置已存储":"保存失败："+(r.error||""),r.ok?"ok":"err");
};
async function loadCloud(){
  const d=await API.get("/api/config");const c=d.config.cloud||{};
  $("cloudEnable").checked=!!c.enabled;$("cloudProvider").value=c.provider||"s3";
  $("cloudEndpoint").value=c.endpoint||"";$("cloudBucket").value=c.bucket||"";
  $("cloudAk").value=c.access_key||"";$("cloudSk").value=c.secret_key||"";
  $("cloudHours").value=c.interval_hours||6;
}

/* ---------------- logs ---------------- */
async function pollLogs(reset){
  if(reset){state.logSeq=0;state.logBuf=[];$("logbox").innerHTML="";}
  try{
    const d=await API.get("/api/logs?after="+state.logSeq);
    state.logSeq=d.seq;
    const box=$("logbox");
    for(const l of d.logs){
      if(state.logLv!=="all"&&l.lvl!==state.logLv)continue;
      state.logBuf.push(l);if(state.logBuf.length>400)state.logBuf.shift();
    }
    box.innerHTML=state.logBuf.map(l=>`<div><span class="t">${l.ts}</span><span class="${l.lvl}">${l.lvl}</span> ${esc(l.msg)}</div>`).join("");
    box.scrollTop=box.scrollHeight;
  }catch(e){}
}
$("logChips").onclick=e=>{
  const c=e.target.closest(".chip");if(!c)return;
  if(c.id==="logClear"){state.logBuf=[];$("logbox").innerHTML="";return;}
  $("logChips").querySelectorAll(".chip[data-lv]").forEach(x=>x.classList.toggle("sel",x===c));
  state.logLv=c.dataset.lv;pollLogs(true);
};
function esc(s){return String(s).replace(/[&<>]/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[m]))}

/* ---------------- docs ---------------- */
async function loadDocs(){
  if(state.docs){renderDocs();return;}
  const d=await API.get("/api/docs");state.docs=d;renderDocs();
}
function renderDocs(){
  const d=state.docs;if(!d)return;
  const para=t=>(t||"").split(/\n\s*\n/).map(p=>`<p>${esc(p).replace(/\n/g,"<br>")}</p>`).join("");
  $("docBox").innerHTML=`<h4>📖 使用说明</h4>${para(d.usage)}
    <h4>⚠️ 注意事项</h4><div class="warnbox">${para(d.caution)}</div>
    <h4>❓ 常见问题</h4>${para(d.faq)}`;
}

/* ---------------- safety-check progress dialog ---------------- */
let jobFinished=false;
function openJob(j){
  if(!j)return;
  jobFinished=false;
  jobOpen=true;
  $("jobBg").classList.add("on");
  $("jobCancel").textContent="取消";
  $("jobDone").style.display="none";
  renderJob(j);
  if(jobTimer)clearInterval(jobTimer);
  jobTimer=setInterval(async()=>{
    try{
      const r=await API.get("/api/job");
      if(r&&r.job)renderJob(r.job);
    }catch(e){}
  },300);
}
function closeJob(){
  $("jobBg").classList.remove("on");
  jobOpen=false;
  if(jobTimer){clearInterval(jobTimer);jobTimer=null;}
}
function jobLine(j){
  const n=x=>(x||0).toLocaleString("en-US");
  const err=` · 错误 ${j.errors||0}`;
  if(j.phase==="scan")  return `读取主机 ${n(j.done)}/${n(j.total)}${err} · ${j.current||"—"}`;
  if(j.phase==="verify")return `读回核对 ${n(j.verified)}/${n(j.total)} · 待核对 ${n(j.pending)}${err} · ${j.current||"—"}`;
  return `Node写入 ${n(j.written)}/${n(j.total)}${err} · ${j.current||"—"}`;
}
function renderJob(j){
  if(!j){closeJob();return;}
  const isStart=j.kind==="start";
  const src=(j.master||"a").toUpperCase(), dst=src==="A"?"B":"A";
  $("jobTitle").textContent=isStart?"启动镜像安全检查":"模式切换安全检测";
  $("jobDesc").textContent=`正在以 ${src} 台为基准对齐 ${dst} 台，并读回核对允许同步的参数。请暂勿操作两台调音台或 All Live，完成会提示可以操作。`;
  $("jobTarget").textContent=(isStart?"建立基线对齐":`切换到${MODE_LABEL[j.mode]||j.mode||""}`)+"…";
  $("jobBar").style.width=(j.pct||0)+"%";
  $("jobLine").textContent=jobLine(j);
  if(j.active||jobFinished)return;
  jobFinished=true;
  const ok=j.phase==="done"&&j.ok;
  const msg=j.message||(ok?"安全检测通过，可以操作调音台":"安全检测未通过");
  $("jobDone").style.display="block";
  $("jobDone").textContent=msg;
  $("jobCancel").textContent="关闭";
  closeJob();  // done: dismiss and report, like the reference dialog
  toast(msg+`（写入 ${j.written||0} · 读回确认 ${j.verified||0}）`,ok?"ok":(j.phase==="cancelled"?"":"err"));
  poll(true);
}
$("jobCancel").onclick=async()=>{
  if($("jobCancel").textContent==="关闭"){closeJob();return;}
  const r=await API.post("/api/job/cancel");
  if(!r.ok){closeJob();return;}
  toast("已请求取消，等待本次处理停止…");
};

/* run status card buttons (workspace 03) */
$("rcPause").onclick=async()=>{
  const s=state.status||{};
  const r=await API.post("/api/pause",{paused:!s.paused});
  if(r.ok){toast(r.paused?"已暂停同步 · 转发停止":"已继续同步",r.paused?"":"ok");poll(true);}
  else toast("操作失败："+(r.error||""),"err");
};
$("rcStop").onclick=()=>stopEngine();
$("rcLogs").onclick=()=>goto("logs");

/* ---------------- sheet / toast ---------------- */
function sheet(title,body,acts,icon){
  $("sheetTitle").textContent=title;$("sheetBody").innerHTML=body;
  $("sheetIc").innerHTML=`<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v5c0 4.6-3 8.4-7 10-4-1.6-7-5.4-7-10V6z"/></svg>`;
  const a=$("sheetActs");a.innerHTML="";
  for(const x of acts){
    const b=document.createElement("button");b.className=x.cls+" big";b.textContent=x.t;
    b.onclick=()=>{$("sheetBg").classList.remove("on");if(x.fn)x.fn()};
    a.appendChild(b);
  }
  $("sheetBg").classList.add("on");
}
$("sheetBg").addEventListener("click",e=>{if(e.target===$("sheetBg"))$("sheetBg").classList.remove("on")});
let toastTimer=null;
function toast(msg,kind){
  const t=$("toast");
  t.innerHTML=`<span class="led ${kind==="err"?"err":kind==="ok"?"on":""}"></span>${esc(msg)}`;
  t.classList.add("on");clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>t.classList.remove("on"),2600);
}

/* ---------------- pywebview bridge (traffic lights) ---------------- */
function bindBridge(){
  if(!window.pywebview||!window.pywebview.api)return;
  $("lights").style.display="flex";
  $("lights").onclick=async e=>{
    const b=e.target.closest("button");if(!b)return;
    const api=window.pywebview.api;
    try{
      if(b.dataset.act==="close")api.close();
      else if(b.dataset.act==="min")api.minimize();
      else api.toggle_maximize();
    }catch(err){}
  };
}
window.addEventListener("pywebviewready",bindBridge);
if(document.readyState!=="loading")bindBridge();else document.addEventListener("DOMContentLoaded",bindBridge);

/* ---------------- poll loop ---------------- */
async function poll(force){
  try{
    const [s,h]=await Promise.all([API.get("/api/status"),API.get("/api/ha")]);
    state.status=s;state.ha=h;
    state.running=!!(s&&s.running);  // global: pages other than home need it too
    renderPill(s);
    // a safety-check pass started (mode switch or start-up alignment):
    // surface the progress dialog wherever the operator is
    const jb=s&&s.sync_job;
    if(jb&&jb.active&&!jobOpen)openJob(jb);
  }catch(e){state.status=null;}
  if(state.page==="home")renderHome();
  if(state.page==="ha")renderHA();
  if(state.page==="config"&&state.running!==undefined){} // config page is static once loaded
}
setInterval(poll,900);
// preload the config cache so 启动镜像 works from any page
API.get("/api/config").then(d=>{cfgCache=d.config;}).catch(()=>{});
poll(true);
</script>
</body>
</html>
"""
