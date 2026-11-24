# -*- coding: utf-8 -*-
"""
PCS 效率与温升测试数据分析内核
================================
定位：测试工程师工具 —— 输入"实测数据"，输出"指标 + 校核 + 报告"。
与纯设计工具的区别：设计工具给参数算结果；本工具给实测数据判合格。

四大模块：
  1) 效率数据：负载点 [{load, pin, pout, u, i, pf, mode}]
     - 三相 PCS：mode='3ph'，可由 U/I/pf 算 P = √3·U·I·pf（U线电压/I线电流）
     - 单相 DC/DC：mode='1ph'，可由 U/I 算 P = U·I
     - 若直接给了 pin/pout（>0）则优先用实测功率，U/I 只做展示
     - 效率 η = Pout/Pin ×100%；损耗 P_loss = Pin − Pout
  2) 加权效率：η_weight = Σ(w_i · η_i) / Σ(w_i)，权重表可编辑（默认欧洲效率权重）
     - 欧洲效率默认负载点 5/10/20/30/50/100%，权重 0.03/0.06/0.13/0.10/0.48/0.20
  3) 温升数据：测点 [{name, series:[{t, temp, loss}]}, ...] + 环境 Ta
     - 热稳态判定：从后往前找，最近 N 分钟内 |dT/dt| < δ 即稳态（默认 δ=0.1 K/min，N=10 min）
     - 稳态温度 T_ss = 稳态窗口内温度均值；温升 ΔT = T_ss − Ta
     - 热阻反推 R_th = ΔT / P_loss_ss（P_loss_ss 取稳态窗口内损耗均值）
  4) 校核判据（逐负载点 / 逐测点 PASS/FAIL）：
     - 效率 η ≥ η_min（默认 98%）
     - 加权效率 ≥ ηw_min（默认 97.5%）
     - 稳态温升 ΔT ≤ ΔT_max（默认 60 K）
     - 实测热阻 R_th ≤ R_th_design×(1+tol)（默认设计热阻 0.4 K/W，容差 20%）
  5) 寿命估算（复用 device-loss 的 Coffin-Manson）：Nf = NF_REF·(ΔT_ref/ΔTj)^m

所有公式集中于此，网页 core 用相同签名复刻，verify_web.js 逐项比对。
中间量全程双精度，只在显示层格式化。参数来源：IEC 61683 / EN 50530 效率测量思路、
CGC/GF004 加权效率权重惯例、热阻稳态判定工程惯例（IEC 60068 温升试验）。
"""
import math

# ==================== 默认校核阈值（可在界面改）====================
ETA_MIN     = 98.0      # 单负载点效率下限 %
ETAW_MIN    = 97.5      # 加权效率下限 %
DT_MAX      = 60.0      # 稳态温升上限 K
RTH_DESIGN  = 0.40      # 设计热阻 K/W
RTH_TOL     = 0.20      # 热阻容差 20%
SS_DELTA    = 0.10      # 稳态判据 |dT/dt| < 0.10 K/min
SS_WINDOW   = 10.0      # 稳态窗口 N 分钟
TA_DEFAULT  = 25.0      # 环境温度 °C

# 加权效率默认权重（欧洲效率惯例，可在界面编辑）
DEFAULT_WEIGHTS = [
    {'load': 5.0,  'w': 0.03},
    {'load': 10.0, 'w': 0.06},
    {'load': 20.0, 'w': 0.13},
    {'load': 30.0, 'w': 0.10},
    {'load': 50.0, 'w': 0.48},
    {'load': 100.0,'w': 0.20},
]

# 寿命（Coffin-Manson）
DT_LIFE_REF = 80.0
NF_REF      = 2e5
M_COFFIN    = 5.0
CYC_PER_YR  = 5e5


def power_from_ui(u, i, pf, mode):
    """由电压/电流/功率因数算功率[W]。mode='3ph' 三相线电压线电流，'1ph' 单相。"""
    if mode == '3ph':
        return math.sqrt(3.0) * u * i * (pf if pf > 0 else 1.0)
    return u * i  # 单相


def eff_point(pt):
    """单个负载点：效率%、损耗W。实测功率优先，否则由 U/I 算。"""
    mode = pt.get('mode', '3ph')
    pin = pt.get('pin', 0.0) or 0.0
    pout = pt.get('pout', 0.0) or 0.0
    if pin <= 0:
        pin = power_from_ui(pt.get('u', 0.0), pt.get('i', 0.0), pt.get('pf', 1.0), mode)
    if pout <= 0:
        # 未给出输出功率：按 pin 减去一个推断损耗不合适，保持 0（界面提示补录）
        pout = pt.get('pout', 0.0) or 0.0
    eta = (pout / pin * 100.0) if pin > 0 else 0.0
    loss = pin - pout
    return {'load': pt.get('load', 0.0), 'pin': pin, 'pout': pout,
            'eta': eta, 'loss': loss, 'mode': mode}


def weighted_efficiency(points, weights):
    """加权效率：按权重表负载率插值取 η，ηw = Σ(w·η)/Σw。"""
    if not points or not weights:
        return 0.0, []
    # 按 load 排序的效率点
    pts = sorted(points, key=lambda p: p['load'])
    total_w, total_weta = 0.0, 0.0
    detail = []
    for wrow in weights:
        target = wrow['load']; w = wrow['w']
        eta = interp_eta(pts, target)
        total_w += w
        total_weta += w * eta
        detail.append({'load': target, 'w': w, 'eta': eta})
    eta_w = total_weta / total_w if total_w > 0 else 0.0
    return eta_w, detail


def interp_eta(pts, target):
    """线性插值取目标负载率下的效率；超出范围取端点。"""
    if not pts:
        return 0.0
    if target <= pts[0]['load']:
        return pts[0]['eta']
    if target >= pts[-1]['load']:
        return pts[-1]['eta']
    for k in range(1, len(pts)):
        if target <= pts[k]['load']:
            a, b = pts[k-1], pts[k]
            if b['load'] == a['load']:
                return b['eta']
            r = (target - a['load']) / (b['load'] - a['load'])
            return a['eta'] + r * (b['eta'] - a['eta'])
    return pts[-1]['eta']


def thermal_point(series, ta, delta, window):
    """单个测点：热稳态判定、稳态温度、温升、热阻反推。
    series: [{t, temp, loss}, ...] 按时间升序。"""
    out = {'ss': False, 't_ss': 0.0, 'temp_ss': 0.0, 'dt': 0.0,
           'ploss_ss': 0.0, 'rth': 0.0, 't_end': 0.0, 'n_win': 0}
    if len(series) < 2:
        out['temp_ss'] = series[0]['temp'] if series else ta
        out['dt'] = out['temp_ss'] - ta
        return out
    ss = sorted(series, key=lambda s: s['t'])
    t_end = ss[-1]['t']
    out['t_end'] = t_end
    # 从后往前找跨度 >= window 的最短稳态窗口（离末端最近、跨度刚够 window 的起点）
    start_i = None
    for i in range(len(ss)-1, -1, -1):
        if t_end - ss[i]['t'] >= window:
            start_i = i
            break
    if start_i is None:
        # 数据总跨度不足 window：用全部数据，标记不稳态
        win = ss
        out['n_win'] = len(win)
        if len(win) >= 2:
            slope = (win[-1]['temp'] - win[0]['temp']) / max(1e-9, win[-1]['t'] - win[0]['t'])
            out['ss'] = abs(slope) < delta
    else:
        win = ss[start_i:]
        out['n_win'] = len(win)
        # 窗口内相邻点最大斜率
        max_slope = 0.0
        for k in range(1, len(win)):
            dt = win[k]['t'] - win[k-1]['t']
            if dt > 0:
                max_slope = max(max_slope, abs((win[k]['temp'] - win[k-1]['temp']) / dt))
        out['ss'] = max_slope < delta
    n = len(win)
    out['temp_ss'] = sum(s['temp'] for s in win) / n
    out['ploss_ss'] = sum(s.get('loss', 0.0) for s in win) / n
    out['dt'] = out['temp_ss'] - ta
    out['rth'] = out['dt'] / out['ploss_ss'] if out['ploss_ss'] > 0 else 0.0
    return out


def life_from_dt(dt):
    """Coffin-Manson 寿命估算。"""
    dj = max(1.0, abs(dt))
    nf = NF_REF * (DT_LIFE_REF / dj) ** M_COFFIN
    return {'nf': nf, 'life_yr': nf / CYC_PER_YR}


def _num_or_none(v):
    """把单元格值转 float；'/'、空串、None、非数字 → None（该点无数据）。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == '' or s == '/':
        return None
    try:
        return float(s)
    except ValueError:
        return None


def solve_snapshot(data):
    """快照表模式：适配 PCS 热测试表（一个 Sheet=一个时间点，每行一个测点）。

    data = {
      'snapshots': [               # 多个时间点快照
         {'time_min': 20, 'rows': [
            {'channel':'CH1-1-1', 'name':'PCS进水口', 'temp':30.25, 'limit':None},
            {'channel':'CH1-1-7', 'name':'交流电容C6', 'temp':37.9,  'limit':95},
            ...
         ]}, ...
      ],
      'baseline': 30.25,           # 基准进水口温度（默认取 CH1-1-1 首值）
      'target': 50.0,              # 折算目标温度（默认 50）
      'loss_w': 0.0,               # 热阻反推用的损耗 W（手工补，0 则不算热阻）
      'rth_design': 0.40, 'rth_tol': 0.20,
    }
    核心业务规则（来自实测表 E 列公式）：折算温度 = 原始温度 − baseline + target
    校核：折算温度 ≤ 限值（逐测点、逐时间点）；测点名可能重复，唯一键用 channel。
    """
    baseline = data.get('baseline')
    target = data.get('target', 50.0)
    loss_w = data.get('loss_w', 0.0)
    rth_design = data.get('rth_design', RTH_DESIGN)
    rth_tol = data.get('rth_tol', RTH_TOL)
    rth_hi = rth_design * (1 + rth_tol)

    snaps = []
    for s in data.get('snapshots', []):
        rows = []
        for r in s.get('rows', []):
            t = _num_or_none(r.get('temp'))
            lim = _num_or_none(r.get('limit'))
            t_conv = (t - baseline + target) if (t is not None and baseline is not None) else None
            ok = (t_conv is not None and lim is not None and t_conv <= lim)
            rows.append({
                'channel': str(r.get('channel', '')).strip(),
                'name': r.get('name', ''),
                'temp': t, 'limit': lim, 't_conv': t_conv,
                'ok': ok if (lim is not None and t_conv is not None) else None,  # None=无判据
                'margin': (lim - t_conv) if (lim is not None and t_conv is not None) else None,
            })
        snaps.append({'time_min': float(s.get('time_min', 0)), 'rows': rows})

    snaps.sort(key=lambda s: s['time_min'])
    times = [s['time_min'] for s in snaps]

    # 按 channel 建测点矩阵（通道号唯一键；忽略空通道）
    channels = []
    seen = set()
    for s in snaps:
        for r in s['rows']:
            c = r['channel']
            if c and c not in seen:
                seen.add(c); channels.append(c)

    matrix = []
    for c in channels:
        raw, conv, limits = [], [], []
        name = ''
        for s in snaps:
            hit = next((r for r in s['rows'] if r['channel'] == c), None)
            if hit:
                name = hit['name'] or name
                raw.append(hit['temp']); conv.append(hit['t_conv']); limits.append(hit['limit'])
            else:
                raw.append(None); conv.append(None); limits.append(None)
        valid_conv = [x for x in conv if x is not None]
        t_max = max(valid_conv) if valid_conv else None
        # 稳态判定：末段两点斜率（快照点少，用相邻点斜率）
        slope = None
        if len(conv) >= 2 and conv[-1] is not None and conv[-2] is not None and times[-1] != times[-2]:
            slope = (conv[-1] - conv[-2]) / (times[-1] - times[-2])
        ok_all = None
        checks = []
        for idx, (tc, lim) in enumerate(zip(conv, limits)):
            if tc is not None and lim is not None:
                checks.append({'time': times[idx], 't_conv': tc, 'limit': lim,
                               'margin': lim - tc, 'ok': tc <= lim})
        if checks:
            ok_all = all(c['ok'] for c in checks)
        # 温升与热阻（用折算温度最大值 - 折算目标作为温升近似；损耗手工补）
        dt = (t_max - target) if t_max is not None else None
        rth = (dt / loss_w) if (dt is not None and loss_w > 0) else None
        matrix.append({
            'channel': c, 'name': name, 'raw': raw, 'conv': conv, 'limit': limits,
            't_max': t_max, 'slope': slope, 'checks': checks, 'ok': ok_all,
            'dt': dt, 'rth': rth,
            'ok_rth': (rth is not None and rth <= rth_hi) if rth is not None else None,
            'life_yr': life_from_dt(dt)['life_yr'] if dt is not None else None,
        })

    n_fail = sum(1 for m in matrix if m['ok'] is False)
    n_judge = sum(1 for m in matrix if m['ok'] is not None)
    all_ok = (n_judge > 0 and n_fail == 0)

    return {
        'snapshots': snaps, 'times': times, 'matrix': matrix,
        'baseline': baseline, 'target': target, 'loss_w': loss_w,
        'n_points': len(matrix), 'n_judge': n_judge, 'n_fail': n_fail,
        'all_ok': all_ok, 'rth_hi': rth_hi,
    }


def solve(data):
    """主求解入口。data 结构与网页 readData() 一致。
    data = {
      'points': [{load,pin,pout,u,i,pf,mode}],   # 效率负载点
      'weights': [{load,w}],                      # 加权权重
      'ta': 环境温度,
      'delta': 稳态斜率阈值, 'window': 稳态窗口min,
      'eta_min','etaw_min','dt_max','rth_design','rth_tol'
    }
    """
    ta = data.get('ta', TA_DEFAULT)
    delta = data.get('delta', SS_DELTA)
    window = data.get('window', SS_WINDOW)
    eta_min = data.get('eta_min', ETA_MIN)
    etaw_min = data.get('etaw_min', ETAW_MIN)
    dt_max = data.get('dt_max', DT_MAX)
    rth_design = data.get('rth_design', RTH_DESIGN)
    rth_tol = data.get('rth_tol', RTH_TOL)

    # 1) 效率负载点
    pts = [eff_point(p) for p in data.get('points', []) if (p.get('pin',0) or p.get('u',0))]
    for p in pts:
        p['ok_eta'] = p['eta'] >= eta_min

    # 2) 加权效率
    weights = data.get('weights', DEFAULT_WEIGHTS)
    eta_w, wdetail = weighted_efficiency(pts, weights)
    ok_etaw = eta_w >= etaw_min

    # 3) 温升测点
    thermals = []
    for tp in data.get('thermals', []):
        r = thermal_point(tp.get('series', []), ta, delta, window)
        r['name'] = tp.get('name', '测点')
        r['ok_dt'] = r['dt'] <= dt_max
        rth_hi = rth_design * (1 + rth_tol)
        r['ok_rth'] = (r['rth'] > 0) and (r['rth'] <= rth_hi)
        r['rth_hi'] = rth_hi
        life = life_from_dt(r['dt'])
        r['nf'] = life['nf']; r['life_yr'] = life['life_yr']
        thermals.append(r)

    # 4) 总校核
    all_ok = all(p['ok_eta'] for p in pts) and ok_etaw and \
             all(t['ok_dt'] and t['ok_rth'] for t in thermals) and len(pts) > 0

    return {'points': pts, 'eta_w': eta_w, 'wdetail': wdetail, 'ok_etaw': ok_etaw,
            'thermals': thermals, 'all_ok': all_ok,
            'eta_min': eta_min, 'etaw_min': etaw_min, 'dt_max': dt_max,
            'rth_design': rth_design, 'rth_tol': rth_tol, 'ta': ta}


if __name__ == '__main__':
    print('=' * 68)
    print('PCS 效率与温升测试数据分析内核 —— 自检')
    print('=' * 68)
    demo = {
        'points': [
            {'load': 10, 'pin': 105.0, 'pout': 100.0, 'mode': '3ph'},
            {'load': 20, 'pin': 204.0, 'pout': 200.0, 'mode': '3ph'},
            {'load': 50, 'pin': 505.0, 'pout': 500.0, 'mode': '3ph'},
            {'load': 100,'pin': 1015.0,'pout': 1000.0,'mode': '3ph'},
        ],
        'weights': DEFAULT_WEIGHTS,
        'ta': 25.0, 'delta': 0.10, 'window': 10.0,
    }
    # 构造温升序列：指数逼近稳态 + 末端平台
    series = []
    for t in [0,5,10,20,30,40,50,60,70,80,90,100]:
        temp = 25 + 55*(1-math.exp(-t/20))
        series.append({'t': t, 'temp': temp, 'loss': 140.0})
    demo['thermals'] = [{'name': 'IGBT壳温', 'series': series}]
    r = solve(demo)
    print('\n--- 效率负载点 ---')
    for p in r['points']:
        print(f"  负载{p['load']:5.1f}%  Pin={p['pin']:7.1f}  Pout={p['pout']:7.1f}  "
              f"η={p['eta']:6.3f}%  损耗={p['loss']:6.1f}W  {'PASS' if p['ok_eta'] else 'FAIL'}")
    print(f"\n加权效率 ηw = {r['eta_w']:.3f}%  ({'PASS' if r['ok_etaw'] else 'FAIL'})")
    print('\n--- 温升测点 ---')
    for t in r['thermals']:
        print(f"  {t['name']}: 稳态={t['ss']}  T_ss={t['temp_ss']:.2f}°C  ΔT={t['dt']:.2f}K  "
              f"Rth={t['rth']:.4f}K/W  寿命={t['life_yr']:.1f}年")
    print(f"\n综合校核: {'PASS' if r['all_ok'] else 'FAIL'}")

    # ---- 快照表模式自检 ----
    print('\n' + '=' * 68)
    print('快照表模式自检（模拟 PCS 热测试表：3 时间点 × 4 测点）')
    print('=' * 68)
    snap_demo = {
        'baseline': 30.25, 'target': 50.0, 'loss_w': 140.0,
        'snapshots': [
            {'time_min': 20, 'rows': [
                {'channel':'CH1-1-1','name':'PCS进水口','temp':30.25,'limit':'/'},
                {'channel':'CH1-1-7','name':'交流电容C6','temp':37.9,'limit':95},
                {'channel':'CH1-1-8','name':'IGBT-A1','temp':'/','limit':120},
                {'channel':'CH1-2-1','name':'交流继电器铜皮','temp':60.0,'limit':85},
                {'channel':'CH1-2-2','name':'交流继电器铜皮','temp':65.0,'limit':85},  # 重名，通道区分
            ]},
            {'time_min': 40, 'rows': [
                {'channel':'CH1-1-1','name':'PCS进水口','temp':31.0,'limit':'/'},
                {'channel':'CH1-1-7','name':'交流电容C6','temp':44.05,'limit':95},
                {'channel':'CH1-1-8','name':'IGBT-A1','temp':70.0,'limit':120},
                {'channel':'CH1-2-1','name':'交流继电器铜皮','temp':68.0,'limit':85},
            ]},
            {'time_min': 60, 'rows': [
                {'channel':'CH1-1-1','name':'PCS进水口','temp':32.0,'limit':'/'},
                {'channel':'CH1-1-7','name':'交流电容C6','temp':45.75,'limit':95},
                {'channel':'CH1-1-8','name':'IGBT-A1','temp':72.0,'limit':120},
                {'channel':'CH1-2-1','name':'交流继电器铜皮','temp':90.0,'limit':85},  # 超限 FAIL
            ]},
        ],
    }
    sr = solve_snapshot(snap_demo)
    print(f"基准={sr['baseline']} 目标={sr['target']} 时间点={sr['times']}")
    print(f"测点数={sr['n_points']} 有判据={sr['n_judge']} FAIL 数={sr['n_fail']} 综合={'PASS' if sr['all_ok'] else 'FAIL'}")
    print(f"{'通道':12s} {'名称':14s} " + ' '.join(f'{int(t)}min折算' for t in sr['times']) + '  最大  校核')
    for m in sr['matrix']:
        convs = ' '.join(('%7.2f' % x if x is not None else '     —') for x in m['conv'])
        print(f"  {m['channel']:10s} {m['name']:12s} {convs}  "
              f"{(('%7.2f'%m['t_max']) if m['t_max'] is not None else '     —')}  "
              f"{'—' if m['ok'] is None else ('PASS' if m['ok'] else 'FAIL')}")
