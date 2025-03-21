# config.py
CONFIG = {
    "random_order": True,      # Рандомный порядок приватных ключей (True/False)
    "delay_min": 15,            # Минимальная задержка между ключами (секунды)
    "delay_max": 25,           # Максимальная задержка между ключами (секунды)
    "accounts_per_proxy": 1,   # Количество аккаунтов на один прокси
    "force_network_selection": False,  # Принудительный выбор сети даже при Amount KING = 0 (True/False)
    "max_threads": 1           # Максимальное количество одновременных потоков
}