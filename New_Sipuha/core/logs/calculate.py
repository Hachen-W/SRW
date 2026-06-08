import pandas as pd

# ВАЖНО: Указываем файл логов производительности из папки logs/, 
# так как именно туда воркер пишет временные метки 'process_message_e2e'
FILE_NAME = 'logs/pyara.csv'  # или 'logs/pytorch.csv'

# 1. Загрузка данных
try:
    # Используем header=0, чтобы Pandas корректно пропустил первую строку, если там есть заголовок
    df = pd.read_csv(FILE_NAME, names=[
        'request_id', 'function_name', 'audio_duration', 'execution_time'
        ], header=0
    )
except FileNotFoundError:
    print(f"Файл {FILE_NAME} не найден. Убедитесь, что запустили воркер и он успел накопить логи.")
    exit()

# БЕЗОПАСНОСТЬ: Принудительно переводим числовые колонки в формат float.
# Если там окажется текст (например, дубликат заголовка), он превратится в NaN.
df['audio_duration'] = pd.to_numeric(df['audio_duration'], errors='coerce')
df['execution_time'] = pd.to_numeric(df['execution_time'], errors='coerce')

# Удаляем строки, где конвертация не удалась
df = df.dropna(subset=['audio_duration', 'execution_time'])

# Отфильтруем строки с нулевой длиной (во избежание деления на ноль)
df = df[df['audio_duration'] > 0].copy()

# Рассчитываем RTF (Real-Time Factor) для каждой операции
df['RTF'] = df['execution_time'] / df['audio_duration']

print("=== СТАТИСТИКА ПО КАЖДОМУ ВЫЧИСЛИТЕЛЬНОМУ БЛОКУ ===")
stats = df.groupby('function_name').agg({
    'execution_time': ['mean', 'var'],
    'RTF': ['mean'],
    'request_id': 'count'
}).rename(columns={'request_id': 'count'})

print(stats)
print("-" * 50)

# 2. Истинные расчеты для M/G/1
# Нас интересует только End-to-End время обслуживания (Ts) каждой заявки.
e2e_df = df[df['function_name'].isin(
    ['process_message_e2e', 'timing_script_e2e']
    )]

if e2e_df.empty:
    print("Внимание: End-to-End метрики (process_message_e2e) не найдены.")
    print("Рассчитываем E[Ts] и Var[Ts] путем агрегации всех этапов по request_id.")
    # Если E2E метрики нет, суммируем время всех функций для КАЖДОГО файла
    total_time_per_request = df.groupby('request_id')['execution_time'].sum()
else:
    # Берем готовое E2E время для каждого файла
    total_time_per_request = e2e_df['execution_time']

# Считаем итоговые параметры
E_Ts = total_time_per_request.mean()
Var_Ts = total_time_per_request.var()
Mean_RTF = e2e_df['RTF'].mean() if not e2e_df.empty else (total_time_per_request / df.groupby('request_id')['audio_duration'].mean()).mean()

print("=== ИТОГОВЫЕ ПАРАМЕТРЫ ДЛЯ МАТЕМАТИЧЕСКОЙ МОДЕЛИ ===")
print(f"Среднее время обслуживания E[Ts]: {E_Ts:.4f} сек.")
print(f"Честная дисперсия времени обслуживания Var(Ts): {Var_Ts:.6f} сек².")
print(f"Средний показатель RTF: {Mean_RTF:.4f}")

if Mean_RTF < 1.0:
    print("\n[+] Система работает быстрее реального времени (RTF < 1).")
else:
    print("\n[-] Система работает медленнее реального времени (RTF >= 1). Очередь будет неизбежно расти.")
