// 验证网页 core（solve + solve_snapshot）与 Python 内核逐项一致
const fs = require('fs'), cp = require('child_process'), vm = require('vm');
const payload = JSON.parse(cp.execSync('python export_core.py', {cwd: __dirname}).toString().trim());
const html = fs.readFileSync('index.html', 'utf8');
const m = html.match(/<script id="core">([\s\S]*?)<\/script>/);
if (!m) { console.error('未找到 core 脚本'); process.exit(1); }
const ctx = {}; vm.createContext(ctx); vm.runInContext(m[1], ctx);

let pass = 0, fail = 0;
function cmp(label, a, b, rel) {
  // 字符串/布尔/null 直接相等比较；数值走容差比较
  const ok = (a === null || b === null || typeof a === 'boolean' || typeof a === 'string') ? (a === b) :
    (Math.abs(a-b) <= (rel||1e-6)*Math.max(1, Math.abs(b)));
  if (ok) pass++; else { fail++; console.log(`  ✗ ${label}: web=${a} py=${b}`); }
}

// ===== 时间序列模式 =====
payload.series.forEach(cs => {
  const w = ctx.solve(cs.data), p = cs.result, tag = cs.name;
  ['eta_w','ok_etaw','all_ok','eta_min','etaw_min','dt_max','rth_design','rth_tol','ta'].forEach(k =>
    cmp(`${tag}.${k}`, w[k], p[k], 1e-7));
  cmp(`${tag}.points.len`, w.points.length, p.points.length);
  w.points.forEach((wp, i) =>
    ['load','pin','pout','eta','loss','ok_eta'].forEach(k => cmp(`${tag}.pt${i}.${k}`, wp[k], p.points[i][k], 1e-7)));
  cmp(`${tag}.wdetail.len`, w.wdetail.length, p.wdetail.length);
  w.wdetail.forEach((wd, i) =>
    ['load','w','eta'].forEach(k => cmp(`${tag}.wd${i}.${k}`, wd[k], p.wdetail[i][k], 1e-7)));
  cmp(`${tag}.thermals.len`, w.thermals.length, p.thermals.length);
  w.thermals.forEach((wt, i) =>
    ['ss','t_ss','temp_ss','dt','ploss_ss','rth','t_end','n_win','ok_dt','ok_rth','rth_hi','nf','life_yr']
      .forEach(k => cmp(`${tag}.th${i}.${k}`, wt[k], p.thermals[i][k], 1e-7)));
});

// ===== 快照表模式 =====
payload.snapshots.forEach(cs => {
  const w = ctx.solve_snapshot(cs.data), p = cs.result, tag = cs.name;
  ['baseline','target','loss_w','n_points','n_judge','n_fail','all_ok','rth_hi'].forEach(k =>
    cmp(`${tag}.${k}`, w[k], p[k], 1e-7));
  cmp(`${tag}.times.len`, w.times.length, p.times.length);
  w.times.forEach((t, i) => cmp(`${tag}.time${i}`, t, p.times[i], 1e-7));
  cmp(`${tag}.snaps.len`, w.snapshots.length, p.snapshots.length);
  w.snapshots.forEach((s, i) => {
    cmp(`${tag}.snap${i}.rows.len`, s.rows.length, p.snapshots[i].rows.length);
    s.rows.forEach((row, j) => {
      cmp(`${tag}.snap${i}.r${j}.channel`, row.channel, p.snapshots[i].rows[j].channel);
      cmp(`${tag}.snap${i}.r${j}.temp`, row.temp, p.snapshots[i].rows[j].temp, 1e-7);
      cmp(`${tag}.snap${i}.r${j}.limit`, row.limit, p.snapshots[i].rows[j].limit, 1e-7);
      cmp(`${tag}.snap${i}.r${j}.t_conv`, row.t_conv, p.snapshots[i].rows[j].t_conv, 1e-7);
      cmp(`${tag}.snap${i}.r${j}.ok`, row.ok, p.snapshots[i].rows[j].ok);
    });
  });
  cmp(`${tag}.matrix.len`, w.matrix.length, p.matrix.length);
  w.matrix.forEach((m, i) => {
    ['channel','name','t_max','slope','ok','dt','rth','ok_rth','life_yr'].forEach(k =>
      cmp(`${tag}.m${i}.${k}`, m[k], p.matrix[i][k], 1e-7));
    ['raw','conv','limit'].forEach(arr => {
      cmp(`${tag}.m${i}.${arr}.len`, m[arr].length, p.matrix[i][arr].length);
      m[arr].forEach((v, j) => cmp(`${tag}.m${i}.${arr}${j}`, v, p.matrix[i][arr][j], 1e-7));
    });
    cmp(`${tag}.m${i}.checks.len`, m.checks.length, p.matrix[i].checks.length);
    m.checks.forEach((c, j) => ['time','t_conv','limit','margin','ok'].forEach(k =>
      cmp(`${tag}.m${i}.ck${j}.${k}`, c[k], p.matrix[i].checks[j][k], 1e-7)));
  });
});

console.log(`\n===== 时间序列 ${payload.series.length} 组 + 快照 ${payload.snapshots.length} 组，合计 ${pass} 通过 / ${fail} 失败 =====`);
process.exit(fail ? 1 : 0);
