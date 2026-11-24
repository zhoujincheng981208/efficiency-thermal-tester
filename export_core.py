# -*- coding: utf-8 -*-
"""导出多组工况的内核结果供 verify_web.js 逐项比对。
每组工况 data 与网页 solve(data) 入参结构一致。"""
import json, math, calc_core as c

# 构造若干工况：不同负载点数、不同测点数、含 U/I 反推功率、不同稳态窗口
cases = []

# 工况1：直接给 Pin/Pout，4 负载点 + 1 测点（指数升温到稳态）
s1 = [{'t': t, 'temp': 25 + 55*(1-math.exp(-t/20)), 'loss': 140.0}
      for t in [0, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]]
cases.append({'name': 'C1-4点1测点', 'data': {
    'points': [
        {'load': 10, 'pin': 105.0, 'pout': 100.0, 'mode': '3ph'},
        {'load': 20, 'pin': 204.0, 'pout': 200.0, 'mode': '3ph'},
        {'load': 50, 'pin': 505.0, 'pout': 500.0, 'mode': '3ph'},
        {'load': 100, 'pin': 1015.0, 'pout': 1000.0, 'mode': '3ph'}],
    'weights': c.DEFAULT_WEIGHTS, 'ta': 25.0, 'delta': 0.10, 'window': 10.0,
    'eta_min': 98.0, 'etaw_min': 97.5, 'dt_max': 60.0,
    'rth_design': 0.40, 'rth_tol': 0.20,
    'thermals': [{'name': 'IGBT壳温', 'series': s1}]}})

# 工况2：U/I/pf 反推三相功率 + 3 测点 + 不同阈值
s2a = [{'t': t, 'temp': 30 + 40*(1-math.exp(-t/15)), 'loss': 100.0} for t in range(0, 61, 5)]
s2b = [{'t': t, 'temp': 28 + 25*(1-math.exp(-t/10)), 'loss': 60.0} for t in range(0, 61, 5)]
s2c = [{'t': t, 'temp': 26 + 12*(1-math.exp(-t/8)), 'loss': 30.0} for t in range(0, 61, 5)]
cases.append({'name': 'C2-UI反推3测点', 'data': {
    'points': [
        {'load': 20, 'u': 690, 'i': 100, 'pf': 0.99, 'mode': '3ph'},
        {'load': 50, 'u': 690, 'i': 250, 'pf': 0.99, 'mode': '3ph'},
        {'load': 100, 'u': 690, 'i': 500, 'pf': 1.0, 'mode': '3ph'}],
    'weights': [{'load': 20, 'w': 0.2}, {'load': 50, 'w': 0.5}, {'load': 100, 'w': 0.3}],
    'ta': 30.0, 'delta': 0.05, 'window': 15.0,
    'eta_min': 97.0, 'etaw_min': 96.0, 'dt_max': 50.0,
    'rth_design': 0.35, 'rth_tol': 0.15,
    'thermals': [
        {'name': 'SiC壳温', 'series': s2a},
        {'name': '散热器', 'series': s2b},
        {'name': '电容', 'series': s2c}]}})

# 工况3：单相 DC/DC + 短序列（不足窗口，测边界）
s3 = [{'t': t, 'temp': 25 + 30*(1-math.exp(-t/12)), 'loss': 80.0} for t in [0, 3, 6, 9]]
cases.append({'name': 'C3-单相短序列', 'data': {
    'points': [
        {'load': 50, 'u': 400, 'i': 100, 'pf': 1, 'mode': '1ph'},
        {'load': 100, 'u': 400, 'i': 200, 'pf': 1, 'mode': '1ph'}],
    'weights': c.DEFAULT_WEIGHTS, 'ta': 20.0, 'delta': 0.10, 'window': 10.0,
    'eta_min': 95.0, 'etaw_min': 94.0, 'dt_max': 40.0,
    'rth_design': 0.5, 'rth_tol': 0.25,
    'thermals': [{'name': 'MOS壳温', 'series': s3}]}})

out = []
for case in cases:
    r = c.solve(case['data'])
    out.append({
        'name': case['name'],
        'data': case['data'],
        'result': r,
    })

# ============ 快照表模式用例 ============
snap_cases = []

# 快照1：用户真实表结构（3 时间点 × 5 测点，含空值'/'、重名测点、超限）
snap_cases.append({'name': 'S1-真实表结构', 'data': {
    'baseline': 30.25, 'target': 50.0, 'loss_w': 140.0,
    'rth_design': 0.40, 'rth_tol': 0.20,
    'snapshots': [
        {'time_min': 20, 'rows': [
            {'channel':'CH1-1-1','name':'PCS进水口','temp':30.25,'limit':'/'},
            {'channel':'CH1-1-7','name':'交流电容C6','temp':37.9,'limit':95},
            {'channel':'CH1-1-8','name':'IGBT-A1','temp':'/','limit':120},
            {'channel':'CH1-2-1','name':'交流继电器铜皮','temp':60.0,'limit':85},
            {'channel':'CH1-2-2','name':'交流继电器铜皮','temp':65.0,'limit':85}  # 重名
        ]},
        {'time_min': 40, 'rows': [
            {'channel':'CH1-1-1','name':'PCS进水口','temp':31.0,'limit':'/'},
            {'channel':'CH1-1-7','name':'交流电容C6','temp':44.05,'limit':95},
            {'channel':'CH1-1-8','name':'IGBT-A1','temp':70.0,'limit':120},
            {'channel':'CH1-2-1','name':'交流继电器铜皮','temp':68.0,'limit':85}
        ]},
        {'time_min': 60, 'rows': [
            {'channel':'CH1-1-1','name':'PCS进水口','temp':32.0,'limit':'/'},
            {'channel':'CH1-1-7','name':'交流电容C6','temp':45.75,'limit':95},
            {'channel':'CH1-1-8','name':'IGBT-A1','temp':72.0,'limit':120},
            {'channel':'CH1-2-1','name':'交流继电器铜皮','temp':90.0,'limit':85}  # 超限 FAIL
        ]},
    ]}})

# 快照2：全部 PASS / 部分时间点缺测点 / 基准不同
snap_cases.append({'name': 'S2-全PASS缺测点', 'data': {
    'baseline': 25.0, 'target': 50.0, 'loss_w': 0,
    'rth_design': 0.5, 'rth_tol': 0.1,
    'snapshots': [
        {'time_min': 10, 'rows': [
            {'channel':'A','name':'测点A','temp':30,'limit':80},
            {'channel':'B','name':'测点B','temp':40,'limit':90},
            {'channel':'C','name':'测点C','temp':35,'limit':85}
        ]},
        {'time_min': 30, 'rows': [
            {'channel':'A','name':'测点A','temp':45,'limit':80},
            {'channel':'C','name':'测点C','temp':50,'limit':85}  # B 缺失
        ]},
        {'time_min': 50, 'rows': [
            {'channel':'A','name':'测点A','temp':50,'limit':80},
            {'channel':'B','name':'测点B','temp':55,'limit':90},
            {'channel':'C','name':'测点C','temp':52,'limit':85}
        ]},
    ]}})

# 快照3：时间点乱序（验证排序）+ 字符串数值 + 空限值
snap_cases.append({'name': 'S3-乱序字符串', 'data': {
    'baseline': 30.0, 'target': 50.0, 'loss_w': 100.0,
    'snapshots': [
        {'time_min': 60, 'rows': [{'channel':'X','name':'X点','temp':'66.5','limit':'95'}]},
        {'time_min': 20, 'rows': [{'channel':'X','name':'X点','temp':'40.2','limit':'95'}]},
        {'time_min': 40, 'rows': [{'channel':'X','name':'X点','temp':55.0,'limit':''}]},
    ]}})

snap_out = []
for cs in snap_cases:
    r = c.solve_snapshot(cs['data'])
    snap_out.append({'name': cs['name'], 'data': cs['data'], 'result': r})

print(json.dumps({'series': out, 'snapshots': snap_out}, ensure_ascii=False))
