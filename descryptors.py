import logging
import ipaddress


# Инициализиция логера
# Метод определения модуля, источника запуска
if sys.argv[0].find('client') == -1:
    # если не клиент то сервер
    logger = logging.getLogger('server')
else:
    # раз не сервер, то клиент
    logger = logging.getLogger('client')


# Дескриптор для проверки порта
class Port:
    def __set__(self, instance, value):
        if not 1023 < value < 65536:
            logger.critical(
                f'Попытка запуска с указанием неподходящего порта {value}. Допустимы адреса с 1024 до 65535.')
            exit(1)
        instance.__dict__[self.name] = value
    def __set_name__(self, owner, name):
        self.name = name


# Дескриптор для проверки IP-адреса
class Addr():
    def __set__(self, instance, value):
        if value:
            try:
                ip = ipaddress.ip_address(value)
            except ValueError as e:
                #LOG.critical(
                #    f'Неверно введен IP-адрес: {e}')
                exit(1)
        instance.__dict__[self.name] = value
    def __set_name__(self, owner, name):
        self.name = name