import socket
import sys
import argparse
import json
import logging
import select
import time
import logs.config_server_log
from errors import IncorrectDataRecivedError
from common.variables import *
from common.utils import *
from decos import log

# Инициализация логирования сервера.
logger = logging.getLogger('server')


# Обработчик сообщений от клиентов, принимает словарь - сообщение от клиента, проверяет корректность, отправляет
#     словарь-ответ в случае необходимости.
@log
def process_client_message(message, messages_list, client, clients, names):
    logger.debug(f'Разбор сообщения от клиента : {message}')
    # Если это сообщение о присутствии, принимаем и отвечаем
    if ACTION in message and message[ACTION] == PRESENCE and TIME in message and USER in message:
        # Если такой пользователь ещё не зарегистрирован, регистрируем, иначе отправляем ответ и завершаем соединение.
        if message[USER][ACCOUNT_NAME] not in names.keys():
            names[message[USER][ACCOUNT_NAME]] = client
            send_message(client, RESPONSE_200)
        else:
            response = RESPONSE_400
            response[ERROR] = 'Имя пользователя уже занято.'
            send_message(client, response)
            clients.remove(client)
            client.close()
        return
    # Если это сообщение, то добавляем его в очередь сообщений. Ответ не требуется.
    elif ACTION in message and message[ACTION] == MESSAGE and DESTINATION in message and TIME in message \
            and SENDER in message and MESSAGE_TEXT in message:
        messages_list.append(message)
        return
    # Если клиент выходит
    elif ACTION in message and message[ACTION] == EXIT and ACCOUNT_NAME in message:
        clients.remove(names[ACCOUNT_NAME])
        names[ACCOUNT_NAME].close()
        del names[ACCOUNT_NAME]
        return
    # Иначе отдаём Bad request
    else:
        response = RESPONSE_400
        response[ERROR] = 'Запрос некорректен.'
        send_message(client, response)
        return


@log
# Функция адресной отправки сообщения определённому клиенту. Принимает словарь сообщение, список зарегистрированых
# пользователей и слушающие сокеты. Ничего не возвращает.
def process_message(message, names, listen_socks):
    if message[DESTINATION] in names and names[message[DESTINATION]] in listen_socks:
        send_message(names[message[DESTINATION]], message)
        logger.info(f'Отправлено сообщение пользователю {message[DESTINATION]} от пользователя {message[SENDER]}.')
    elif message[DESTINATION] in names and names[message[DESTINATION]] not in listen_socks:
        raise ConnectionError
    else:
        logger.error(
            f'Пользователь {message[DESTINATION]} не зарегистрирован на сервере, отправка сообщения невозможна.')


# Парсер аргументов коммандной строки.
@log
def arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', default=DEFAULT_PORT, type=int, nargs='?')
    parser.add_argument('-a', default='', nargs='?')
    namespace = parser.parse_args(sys.argv[1:])
    listen_address = namespace.a
    listen_port = namespace.p

    # проверка получения корретного номера порта для работы сервера.
    if not 1023 < listen_port < 65536:
        logger.critical(
            f'Попытка запуска сервера с указанием неподходящего порта {listen_port}. Допустимы адреса с 1024 до 65535.')
        exit(1)

    return listen_address, listen_port


def main():
    # Загрузка параметров командной строки, если нет параметров, то задаём значения по умоланию.
    listen_address, listen_port = arg_parser()

    logger.info(
        f'Запущен сервер, порт для подключений: {listen_port} , адрес с которого принимаются подключения: {listen_address}. Если адрес не указан, принимаются соединения с любых адресов.')
    # Готовим сокет
    transport = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    transport.bind((listen_address, listen_port))
    transport.settimeout(0.5)

    # список клиентов , очередь сообщений
    clients = []
    messages = []

    # Словарь, содержащий имена пользователей и соответствующие им сокеты.
    names = dict()

    # Слушаем порт
    transport.listen(MAX_CONNECTIONS)
    # Основной цикл программы сервера
    while True:
        # Ждём подключения, если таймаут вышел, ловим исключение.
        try:
            client, client_address = transport.accept()
        except OSError:
            pass
        else:
            logger.info(f'Установлено соедение с ПК {client_address}')
            clients.append(client)

        recv_data_lst = []
        send_data_lst = []
        err_lst = []
        # Проверяем на наличие ждущих клиентов
        try:
            if clients:
                recv_data_lst, send_data_lst, err_lst = select.select(clients, clients, [], 0)
        except OSError:
            pass

        # принимаем сообщения и если ошибка, исключаем клиента.
        if recv_data_lst:
            for client_with_message in recv_data_lst:
                try:
                    process_client_message(get_message(client_with_message), messages, client_with_message, clients,
                                           names)
                except:
                    logger.info(f'Клиент {client_with_message.getpeername()} отключился от сервера.')
                    clients.remove(client_with_message)

        # Если есть сообщения, обрабатываем каждое.
        for i in messages:
            try:
                process_message(i, names, send_data_lst)
            except:
                logger.info(f'Связь с клиентом с именем {i[DESTINATION]} была потеряна')
                clients.remove(names[i[DESTINATION]])
                del names[i[DESTINATION]]
        messages.clear()


if __name__ == '__main__':
    main()
