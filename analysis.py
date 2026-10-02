"""计算轨迹、风场与任务状态统计量。"""
import math
def percentile(values, fraction):
    if not values:
        return None
    data = sorted(values)
    index = (len(data) - 1) * fraction
    left = math.floor(index)
    right = math.ceil(index)
    return data[left] + (data[right] - data[left]) * (index - left)
def decimate(rows, maximum=1600):
    """等索引抽取且保留首尾；导出的CSV 仍保留所有采样。"""
    if maximum < 2:
        raise ValueError('绘图采样上限必须至少为2')
    if len(rows) <= maximum:
        return rows
    indices = [round(i * (len(rows) - 1) / (maximum - 1))
               for i in range(maximum)]
    return [rows[i] for i in indices]
def metrics(result):
    rows = result['samples']
    path_length = 0.0
    previous = [0, 0, 0]
    mode_counts = {}
    for row in rows:
        point = [row['x'], row['y'], row['z']]
        path_length += math.dist(previous, point)
        previous = point
        mode_counts[row['mode']] = mode_counts.get(row['mode'], 0) + 1
    distances = [r['target_distance'] for r in rows]
    latencies = [r['virtual_latency'] * 1000 for r in rows]
    valid = sum(r['sensor_valid'] for r in rows)
    wind_errors = [abs(r.get('wind_speed', 0) - r.get('wind_estimate_speed', 0))
                   for r in rows]
    gust_samples = sum(r.get('wind_regime') in {'GUST', 'TURBULENT', 'LIMIT'}
                       for r in rows)
    count = len(rows)
    return {
        'path_length_m': path_length,
        'max_altitude_m': max((r['z'] for r in rows), default=0),
        'mean_target_distance_m': sum(distances) / count if count else None,
        'p95_target_distance_m': percentile(distances, 0.95),
        'p95_virtual_latency_ms': percentile(latencies, 0.95),
        'sensor_availability': valid / count if count else None,
        'command_update_ratio': result['summary']['command_updates'] / count
        if count else None,
        'mean_wind_estimation_error_mps': (sum(wind_errors) / count
                                           if count else None),
        'gust_sample_ratio': gust_samples / count if count else None,
        'mode_samples': mode_counts,
    }
def public_result(record):
    result = record['result']
    return {'id': record['id'], 'name': record['name'],
            'created': record['created'], 'config': result['config'],
            'summary': result['summary'], 'events': result['events'],
            'metrics': metrics(result),
            'samples': decimate(result['samples']),
            'plot_sample_limit': 1600}
