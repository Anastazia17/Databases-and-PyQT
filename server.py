import socket
import sys
import argparse
import json
import logging
import select
import time
import threading
import logs.config_server_log
from errors import IncorrectDataRecivedError
from common.variables import *
from common.utils import *
from decos import log
from descryptors import Port
from metaclasses import ServerMaker
from server_database import ServerStorage

# Инициализация логирования сервера.
logger = logging.getLogger('server')

# Парсер аргументов коммандной строки.
@log
def arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', default=DEFAULT_PORT, type=int, nargs='?')
    parser.add_argument('-a', default='', nargs='?')
    namespace = parser.parse_args(sys.argv[1:])
    listen_address = namespace.a
    listen_port = namespace.p
    return listen_address, listen_port

# Основной класс сервера
class Server(threading.Thread, metaclass=ServerMaker):
    port = Port()

    def __init__(self, listen_address, listen_port, database):
        # Параментры подключения
        self.addr = listen_address
        self.port = listen_port

        # База данных сервера
        self.database = database

        # Список подключённых клиентов.
        self.clients = []

        # Список сообщений на отправку.
        self.messages = []

        # Словарь содержащий сопоставленные имена и соответствующие им сокеты.
        self.names = dict()

        # Конструктор предка
        super().__init__()

    def init_socket(self):
        logger.info(
            f'Запущен сервер, порт для подключений: {self.port} , адрес с которого принимаются подключения: {self.addr}. Если адрес не указан, принимаются соединения с любых адресов.')
        # Готовим сокет
        transport = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        transport.bind((self.addr, self.port))
        transport.settimeout(0.5)

        # Начинаем слушать сокет.
        self.sock = transport
        self.sock.listen()

    def run(self):
        # Инициализация Сокета
        self.init_socket()

        # Основной цикл программы сервера
        while True:
            # Ждём подключения, если таймаут вышел, ловим исключение.
            try:
                client, client_address = self.sock.accept()
            except OSError:
                pass
            else:
                logger.info(f'Установлено соедение с ПК {client_address}')
                self.clients.append(client)

            recv_data_lst = []
            send_data_lst = []
            err_lst = []
            # Проверяем на наличие ждущих клиентов
            try:
                if self.clients:
                    recv_data_lst, send_data_lst, err_lst = select.select(self.clients, self.clients, [], 0)
            except OSError:
                pass

            # принимаем сообщения и если ошибка, исключаем клиента.
            if recv_data_lst:
                for client_with_message in recv_data_lst:
                    try:
                        self.process_client_message(get_message(client_with_message), client_with_message)
                    except:
                        logger.info(f'Клиент {client_with_message.getpeername()} отключился от сервера.')
                        self.clients.remove(client_with_message)

            # Если есть сообщения, обрабатываем каждое.
            for message in self.messages:
                try:
                    self.process_message(message, send_data_lst)
                except:
                    logger.info(f'Связь с клиентом с именем {message[DESTINATION]} была потеряна')
                    self.clients.remove(self.names[message[DESTINATION]])
                    del self.names[message[DESTINATION]]
            self.messages.clear()

    # Функция адресной отправки сообщения определённому клиенту. Принимает словарь сообщение, список зарегистрированых
    # пользователей и слушающие сокеты. Ничего не возвращает.
    def process_message(self, message, listen_socks):
        if message[DESTINATION] in self.names and self.names[message[DESTINATION]] in listen_socks:
            send_message(self.names[message[DESTINATION]], message)
            logger.info(f'Отправлено сообщение пользователю {message[DESTINATION]} от пользователя {message[SENDER]}.')
        elif message[DESTINATION] in self.names and self.names[message[DESTINATION]] not in listen_socks:
            raise ConnectionError
        else:
            logger.error(
                f'Пользователь {message[DESTINATION]} не зарегистрирован на сервере, отправка сообщения невозможна.')

    # Обработчик сообщений от клиентов, принимает словарь - сообщение от клиента, проверяет корректность, отправляет
    #     словарь-ответ в случае необходимости.
    def process_client_message(self, message, client):
        logger.debug(f'Разбор сообщения от клиента : {message}')
        # Если это сообщение о присутствии, принимаем и отвечаем
        if ACTION in message and message[ACTION] == PRESENCE and TIME in message and USER in message:
            # Если такой пользователь ещё не зарегистрирован, регистрируем, иначе отправляем ответ и завершаем соединение.
            if message[USER][ACCOUNT_NAME] not in self.names.keys():
                self.names[message[USER][ACCOUNT_NAME]] = client
                client_ip, client_port = client.getpeername()
                self.database.user_login(message[USER][ACCOUNT_NAME], client_ip, client_port)
                send_message(client, RESPONSE_200)
            else:
                response = RESPONSE_400
                response[ERROR] = 'Имя пользователя уже занято.'
                send_message(client, response)
                self.clients.remove(client)
                client.close()
            return
        # Если это сообщение, то добавляем его в очередь сообщений. Ответ не требуется.
        elif ACTION in message and message[ACTION] == MESSAGE and DESTINATION in message and TIME in message \
                and SENDER in message and MESSAGE_TEXT in message:
            self.messages.append(message)
            return
        # Если клиент выходит
        elif ACTION in message and message[ACTION] == EXIT and ACCOUNT_NAME in message:
            self.database.user_logout(message[ACCOUNT_NAME])
            self.clients.remove(self.names[message[ACCOUNT_NAME]])
            self.names[message[ACCOUNT_NAME]].close()
            del self.names[message[ACCOUNT_NAME]]
            return
        # Иначе отдаём Bad request
        else:
            response = RESPONSE_400
            response[ERROR] = 'Запрос некорректен.'
            send_message(client, response)
            return


def print_help():
    print('Поддерживаемые комманды:')
    print('users - список известных пользователей')
    print('connected - список подключенных пользователей')
    print('loghist - история входов пользователя')
    print('exit - завершение работы сервера.')
    print('help - вывод справки по поддерживаемым командам')


def main():
    # Загрузка параметров командной строки, если нет параметров, то задаём значения по умоланию.
    listen_address, listen_port = arg_parser()

    # Инициализация базы данных
    database = ServerStorage()

    # Создание экземпляра класса - сервера и его запуск:
    server = Server(listen_address, listen_port, database)
    server.daemon = True
    server.start()

    # Печатаем справку:
    print_help()

    # Основной цикл сервера:
    while True:
        command = input('Введите комманду: ')
        if command == 'help':
            print_help()
        elif command == 'exit':
            break
        elif command == 'users':
            for user in sorted(database.users_list()):
                print(f'Пользователь {user[0]}, последний вход: {user[1]}')
        elif command == 'connected':
            for user in sorted(database.active_users_list()):
                print(f'Пользователь {user[0]}, подключен: {user[1]}:{user[2]}, время установки соединения: {user[3]}')
        elif command == 'loghist':
            name = input('Введите имя пользователя для просмотра истории. Для вывода всей истории, просто нажмите Enter: ')
            for user in sorted(database.login_history(name)):
                print(f'Пользователь: {user[0]} время входа: {user[1]}. Вход с: {user[2]}:{user[3]}')
        else:
            print('Команда не распознана.')


if __name__ == '__main__':
    main()


"""
Результат выполнения:

Instruction(opname='LOAD_NAME', opcode=101, arg=0, argval='__main__', argrepr='__main__', offset=0, starts_line=1, is_jump_target=False)
Instruction(opname='RETURN_VALUE', opcode=83, arg=None, argval=None, argrepr='', offset=2, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_NAME', opcode=101, arg=0, argval='Server', argrepr='Server', offset=0, starts_line=1, is_jump_target=False)
Instruction(opname='RETURN_VALUE', opcode=83, arg=None, argval=None, argrepr='', offset=2, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='listen_address', argrepr='listen_address', offset=0, starts_line=40, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=2, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_ATTR', opcode=95, arg=0, argval='addr', argrepr='addr', offset=4, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=2, argval='listen_port', argrepr='listen_port', offset=6, starts_line=41, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=8, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_ATTR', opcode=95, arg=1, argval='port', argrepr='port', offset=10, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=3, argval='database', argrepr='database', offset=12, starts_line=44, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=14, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_ATTR', opcode=95, arg=2, argval='database', argrepr='database', offset=16, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_LIST', opcode=103, arg=0, argval=0, argrepr='', offset=18, starts_line=47, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=20, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_ATTR', opcode=95, arg=3, argval='clients', argrepr='clients', offset=22, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_LIST', opcode=103, arg=0, argval=0, argrepr='', offset=24, starts_line=50, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=26, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_ATTR', opcode=95, arg=4, argval='messages', argrepr='messages', offset=28, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=5, argval='dict', argrepr='dict', offset=30, starts_line=53, is_jump_target=False)
Instruction(opname='CALL_FUNCTION', opcode=131, arg=0, argval=0, argrepr='', offset=32, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=34, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_ATTR', opcode=95, arg=6, argval='names', argrepr='names', offset=36, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=7, argval='super', argrepr='super', offset=38, starts_line=56, is_jump_target=False)
Instruction(opname='CALL_FUNCTION', opcode=131, arg=0, argval=0, argrepr='', offset=40, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=8, argval='__init__', argrepr='__init__', offset=42, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=0, argval=0, argrepr='', offset=44, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=46, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=0, argval=None, argrepr='None', offset=48, starts_line=None, is_jump_target=False)
Instruction(opname='RETURN_VALUE', opcode=83, arg=None, argval=None, argrepr='', offset=50, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=0, argval='logger', argrepr='logger', offset=0, starts_line=59, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=1, argval='info', argrepr='info', offset=2, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=1, argval='Запущен сервер, порт для подключений: ', argrepr="'Запущен сервер, порт для подключений: '", offset=4, starts_line=60, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=6, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=2, argval='port', argrepr='port', offset=8, starts_line=None, is_jump_target=False)
Instruction(opname='FORMAT_VALUE', opcode=155, arg=0, argval=(None, False), argrepr='', offset=10, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=2, argval=' , адрес с которого принимаются подключения: ', argrepr="' , адрес с которого принимаются подключения: '", offset=12, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=14, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=3, argval='addr', argrepr='addr', offset=16, starts_line=None, is_jump_target=False)
Instruction(opname='FORMAT_VALUE', opcode=155, arg=0, argval=(None, False), argrepr='', offset=18, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=3, argval='. Если адрес не указан, принимаются соединения с любых адресов.', argrepr="'. Если адрес не указан, принимаются соединения с любых адресов.'", offset=20, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_STRING', opcode=157, arg=5, argval=5, argrepr='', offset=22, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=24, starts_line=59, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=26, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=4, argval='socket', argrepr='socket', offset=28, starts_line=62, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=4, argval='socket', argrepr='socket', offset=30, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=4, argval='socket', argrepr='socket', offset=32, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=5, argval='AF_INET', argrepr='AF_INET', offset=34, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=4, argval='socket', argrepr='socket', offset=36, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=6, argval='SOCK_STREAM', argrepr='SOCK_STREAM', offset=38, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=2, argval=2, argrepr='', offset=40, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_FAST', opcode=125, arg=1, argval='transport', argrepr='transport', offset=42, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='transport', argrepr='transport', offset=44, starts_line=63, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=7, argval='bind', argrepr='bind', offset=46, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=48, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=3, argval='addr', argrepr='addr', offset=50, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=52, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=2, argval='port', argrepr='port', offset=54, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_TUPLE', opcode=102, arg=2, argval=2, argrepr='', offset=56, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=58, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=60, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='transport', argrepr='transport', offset=62, starts_line=64, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=8, argval='settimeout', argrepr='settimeout', offset=64, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=4, argval=0.5, argrepr='0.5', offset=66, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=68, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=70, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='transport', argrepr='transport', offset=72, starts_line=67, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=74, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_ATTR', opcode=95, arg=9, argval='sock', argrepr='sock', offset=76, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=78, starts_line=68, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=9, argval='sock', argrepr='sock', offset=80, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=10, argval='listen', argrepr='listen', offset=82, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=0, argval=0, argrepr='', offset=84, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=86, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=0, argval=None, argrepr='None', offset=88, starts_line=None, is_jump_target=False)
Instruction(opname='RETURN_VALUE', opcode=83, arg=None, argval=None, argrepr='', offset=90, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=0, starts_line=72, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=0, argval='init_socket', argrepr='init_socket', offset=2, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=0, argval=0, argrepr='', offset=4, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=6, starts_line=None, is_jump_target=False)
Instruction(opname='SETUP_FINALLY', opcode=122, arg=18, argval=28, argrepr='to 28', offset=8, starts_line=77, is_jump_target=True)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=10, starts_line=78, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=1, argval='sock', argrepr='sock', offset=12, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=2, argval='accept', argrepr='accept', offset=14, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=0, argval=0, argrepr='', offset=16, starts_line=None, is_jump_target=False)
Instruction(opname='UNPACK_SEQUENCE', opcode=92, arg=2, argval=2, argrepr='', offset=18, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_FAST', opcode=125, arg=1, argval='client', argrepr='client', offset=20, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_FAST', opcode=125, arg=2, argval='client_address', argrepr='client_address', offset=22, starts_line=None, is_jump_target=False)
Instruction(opname='POP_BLOCK', opcode=87, arg=None, argval=None, argrepr='', offset=24, starts_line=None, is_jump_target=False)
Instruction(opname='JUMP_FORWARD', opcode=110, arg=20, argval=48, argrepr='to 48', offset=26, starts_line=None, is_jump_target=False)
Instruction(opname='DUP_TOP', opcode=4, arg=None, argval=None, argrepr='', offset=28, starts_line=79, is_jump_target=True)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=3, argval='OSError', argrepr='OSError', offset=30, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=10, argval='exception match', argrepr='exception match', offset=32, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=46, argval=46, argrepr='', offset=34, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=36, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=38, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=40, starts_line=None, is_jump_target=False)
Instruction(opname='POP_EXCEPT', opcode=89, arg=None, argval=None, argrepr='', offset=42, starts_line=80, is_jump_target=False)
Instruction(opname='JUMP_FORWARD', opcode=110, arg=30, argval=76, argrepr='to 76', offset=44, starts_line=None, is_jump_target=False)
Instruction(opname='END_FINALLY', opcode=88, arg=None, argval=None, argrepr='', offset=46, starts_line=None, is_jump_target=True)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=4, argval='logger', argrepr='logger', offset=48, starts_line=82, is_jump_target=True)
Instruction(opname='LOAD_METHOD', opcode=160, arg=5, argval='info', argrepr='info', offset=50, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=1, argval='Установлено соедение с ПК ', argrepr="'Установлено соедение с ПК '", offset=52, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=2, argval='client_address', argrepr='client_address', offset=54, starts_line=None, is_jump_target=False)
Instruction(opname='FORMAT_VALUE', opcode=155, arg=0, argval=(None, False), argrepr='', offset=56, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_STRING', opcode=157, arg=2, argval=2, argrepr='', offset=58, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=60, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=62, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=64, starts_line=83, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=6, argval='clients', argrepr='clients', offset=66, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=7, argval='append', argrepr='append', offset=68, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='client', argrepr='client', offset=70, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=72, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=74, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_LIST', opcode=103, arg=0, argval=0, argrepr='', offset=76, starts_line=85, is_jump_target=True)
Instruction(opname='STORE_FAST', opcode=125, arg=3, argval='recv_data_lst', argrepr='recv_data_lst', offset=78, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_LIST', opcode=103, arg=0, argval=0, argrepr='', offset=80, starts_line=86, is_jump_target=False)
Instruction(opname='STORE_FAST', opcode=125, arg=4, argval='send_data_lst', argrepr='send_data_lst', offset=82, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_LIST', opcode=103, arg=0, argval=0, argrepr='', offset=84, starts_line=87, is_jump_target=False)
Instruction(opname='STORE_FAST', opcode=125, arg=5, argval='err_lst', argrepr='err_lst', offset=86, starts_line=None, is_jump_target=False)
Instruction(opname='SETUP_FINALLY', opcode=122, arg=36, argval=126, argrepr='to 126', offset=88, starts_line=89, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=90, starts_line=90, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=6, argval='clients', argrepr='clients', offset=92, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=122, argval=122, argrepr='', offset=94, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=8, argval='select', argrepr='select', offset=96, starts_line=91, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=8, argval='select', argrepr='select', offset=98, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=100, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=6, argval='clients', argrepr='clients', offset=102, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=104, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=6, argval='clients', argrepr='clients', offset=106, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_LIST', opcode=103, arg=0, argval=0, argrepr='', offset=108, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=2, argval=0, argrepr='0', offset=110, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=4, argval=4, argrepr='', offset=112, starts_line=None, is_jump_target=False)
Instruction(opname='UNPACK_SEQUENCE', opcode=92, arg=3, argval=3, argrepr='', offset=114, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_FAST', opcode=125, arg=3, argval='recv_data_lst', argrepr='recv_data_lst', offset=116, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_FAST', opcode=125, arg=4, argval='send_data_lst', argrepr='send_data_lst', offset=118, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_FAST', opcode=125, arg=5, argval='err_lst', argrepr='err_lst', offset=120, starts_line=None, is_jump_target=False)
Instruction(opname='POP_BLOCK', opcode=87, arg=None, argval=None, argrepr='', offset=122, starts_line=None, is_jump_target=True)
Instruction(opname='JUMP_FORWARD', opcode=110, arg=20, argval=146, argrepr='to 146', offset=124, starts_line=None, is_jump_target=False)
Instruction(opname='DUP_TOP', opcode=4, arg=None, argval=None, argrepr='', offset=126, starts_line=92, is_jump_target=True)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=3, argval='OSError', argrepr='OSError', offset=128, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=10, argval='exception match', argrepr='exception match', offset=130, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=144, argval=144, argrepr='', offset=132, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=134, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=136, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=138, starts_line=None, is_jump_target=False)
Instruction(opname='POP_EXCEPT', opcode=89, arg=None, argval=None, argrepr='', offset=140, starts_line=93, is_jump_target=False)
Instruction(opname='JUMP_FORWARD', opcode=110, arg=2, argval=146, argrepr='to 146', offset=142, starts_line=None, is_jump_target=False)
Instruction(opname='END_FINALLY', opcode=88, arg=None, argval=None, argrepr='', offset=144, starts_line=None, is_jump_target=True)
Instruction(opname='LOAD_FAST', opcode=124, arg=3, argval='recv_data_lst', argrepr='recv_data_lst', offset=146, starts_line=96, is_jump_target=True)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=228, argval=228, argrepr='', offset=148, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=3, argval='recv_data_lst', argrepr='recv_data_lst', offset=150, starts_line=97, is_jump_target=False)
Instruction(opname='GET_ITER', opcode=68, arg=None, argval=None, argrepr='', offset=152, starts_line=None, is_jump_target=False)
Instruction(opname='FOR_ITER', opcode=93, arg=72, argval=228, argrepr='to 228', offset=154, starts_line=None, is_jump_target=True)
Instruction(opname='STORE_FAST', opcode=125, arg=6, argval='client_with_message', argrepr='client_with_message', offset=156, starts_line=None, is_jump_target=False)
Instruction(opname='SETUP_FINALLY', opcode=122, arg=20, argval=180, argrepr='to 180', offset=158, starts_line=98, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=160, starts_line=99, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=9, argval='process_client_message', argrepr='process_client_message', offset=162, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=10, argval='get_message', argrepr='get_message', offset=164, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=6, argval='client_with_message', argrepr='client_with_message', offset=166, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_FUNCTION', opcode=131, arg=1, argval=1, argrepr='', offset=168, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=6, argval='client_with_message', argrepr='client_with_message', offset=170, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=2, argval=2, argrepr='', offset=172, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=174, starts_line=None, is_jump_target=False)
Instruction(opname='POP_BLOCK', opcode=87, arg=None, argval=None, argrepr='', offset=176, starts_line=None, is_jump_target=False)
Instruction(opname='JUMP_ABSOLUTE', opcode=113, arg=154, argval=154, argrepr='', offset=178, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=180, starts_line=100, is_jump_target=True)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=182, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=184, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=4, argval='logger', argrepr='logger', offset=186, starts_line=101, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=5, argval='info', argrepr='info', offset=188, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=3, argval='Клиент ', argrepr="'Клиент '", offset=190, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=6, argval='client_with_message', argrepr='client_with_message', offset=192, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=11, argval='getpeername', argrepr='getpeername', offset=194, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=0, argval=0, argrepr='', offset=196, starts_line=None, is_jump_target=False)
Instruction(opname='FORMAT_VALUE', opcode=155, arg=0, argval=(None, False), argrepr='', offset=198, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=4, argval=' отключился от сервера.', argrepr="' отключился от сервера.'", offset=200, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_STRING', opcode=157, arg=3, argval=3, argrepr='', offset=202, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=204, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=206, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=208, starts_line=102, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=6, argval='clients', argrepr='clients', offset=210, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=12, argval='remove', argrepr='remove', offset=212, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=6, argval='client_with_message', argrepr='client_with_message', offset=214, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=216, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=218, starts_line=None, is_jump_target=False)
Instruction(opname='POP_EXCEPT', opcode=89, arg=None, argval=None, argrepr='', offset=220, starts_line=None, is_jump_target=False)
Instruction(opname='JUMP_ABSOLUTE', opcode=113, arg=154, argval=154, argrepr='', offset=222, starts_line=None, is_jump_target=False)
Instruction(opname='END_FINALLY', opcode=88, arg=None, argval=None, argrepr='', offset=224, starts_line=None, is_jump_target=False)
Instruction(opname='JUMP_ABSOLUTE', opcode=113, arg=154, argval=154, argrepr='', offset=226, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=228, starts_line=105, is_jump_target=True)
Instruction(opname='LOAD_ATTR', opcode=106, arg=13, argval='messages', argrepr='messages', offset=230, starts_line=None, is_jump_target=False)
Instruction(opname='GET_ITER', opcode=68, arg=None, argval=None, argrepr='', offset=232, starts_line=None, is_jump_target=False)
Instruction(opname='FOR_ITER', opcode=93, arg=90, argval=326, argrepr='to 326', offset=234, starts_line=None, is_jump_target=True)
Instruction(opname='STORE_FAST', opcode=125, arg=7, argval='message', argrepr='message', offset=236, starts_line=None, is_jump_target=False)
Instruction(opname='SETUP_FINALLY', opcode=122, arg=16, argval=256, argrepr='to 256', offset=238, starts_line=106, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=240, starts_line=107, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=14, argval='process_message', argrepr='process_message', offset=242, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=7, argval='message', argrepr='message', offset=244, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=4, argval='send_data_lst', argrepr='send_data_lst', offset=246, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=2, argval=2, argrepr='', offset=248, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=250, starts_line=None, is_jump_target=False)
Instruction(opname='POP_BLOCK', opcode=87, arg=None, argval=None, argrepr='', offset=252, starts_line=None, is_jump_target=False)
Instruction(opname='JUMP_ABSOLUTE', opcode=113, arg=234, argval=234, argrepr='', offset=254, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=256, starts_line=108, is_jump_target=True)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=258, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=260, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=4, argval='logger', argrepr='logger', offset=262, starts_line=109, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=5, argval='info', argrepr='info', offset=264, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=5, argval='Связь с клиентом с именем ', argrepr="'Связь с клиентом с именем '", offset=266, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=7, argval='message', argrepr='message', offset=268, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=15, argval='DESTINATION', argrepr='DESTINATION', offset=270, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=272, starts_line=None, is_jump_target=False)
Instruction(opname='FORMAT_VALUE', opcode=155, arg=0, argval=(None, False), argrepr='', offset=274, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=6, argval=' была потеряна', argrepr="' была потеряна'", offset=276, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_STRING', opcode=157, arg=3, argval=3, argrepr='', offset=278, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=280, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=282, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=284, starts_line=110, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=6, argval='clients', argrepr='clients', offset=286, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=12, argval='remove', argrepr='remove', offset=288, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=290, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=16, argval='names', argrepr='names', offset=292, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=7, argval='message', argrepr='message', offset=294, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=15, argval='DESTINATION', argrepr='DESTINATION', offset=296, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=298, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=300, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=302, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=304, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=306, starts_line=111, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=16, argval='names', argrepr='names', offset=308, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=7, argval='message', argrepr='message', offset=310, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=15, argval='DESTINATION', argrepr='DESTINATION', offset=312, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=314, starts_line=None, is_jump_target=False)
Instruction(opname='DELETE_SUBSCR', opcode=61, arg=None, argval=None, argrepr='', offset=316, starts_line=None, is_jump_target=False)
Instruction(opname='POP_EXCEPT', opcode=89, arg=None, argval=None, argrepr='', offset=318, starts_line=None, is_jump_target=False)
Instruction(opname='JUMP_ABSOLUTE', opcode=113, arg=234, argval=234, argrepr='', offset=320, starts_line=None, is_jump_target=False)
Instruction(opname='END_FINALLY', opcode=88, arg=None, argval=None, argrepr='', offset=322, starts_line=None, is_jump_target=False)
Instruction(opname='JUMP_ABSOLUTE', opcode=113, arg=234, argval=234, argrepr='', offset=324, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=326, starts_line=112, is_jump_target=True)
Instruction(opname='LOAD_ATTR', opcode=106, arg=13, argval='messages', argrepr='messages', offset=328, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=17, argval='clear', argrepr='clear', offset=330, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=0, argval=0, argrepr='', offset=332, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=334, starts_line=None, is_jump_target=False)
Instruction(opname='JUMP_ABSOLUTE', opcode=113, arg=8, argval=8, argrepr='', offset=336, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=0, argval=None, argrepr='None', offset=338, starts_line=None, is_jump_target=False)
Instruction(opname='RETURN_VALUE', opcode=83, arg=None, argval=None, argrepr='', offset=340, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=0, starts_line=117, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=0, argval='DESTINATION', argrepr='DESTINATION', offset=2, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=4, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=6, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=1, argval='names', argrepr='names', offset=8, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=10, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=86, argval=86, argrepr='', offset=12, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=14, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=1, argval='names', argrepr='names', offset=16, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=18, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=0, argval='DESTINATION', argrepr='DESTINATION', offset=20, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=22, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=24, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=2, argval='listen_socks', argrepr='listen_socks', offset=26, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=28, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=86, argval=86, argrepr='', offset=30, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=2, argval='send_message', argrepr='send_message', offset=32, starts_line=118, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=34, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=1, argval='names', argrepr='names', offset=36, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=38, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=0, argval='DESTINATION', argrepr='DESTINATION', offset=40, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=42, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=44, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=46, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_FUNCTION', opcode=131, arg=2, argval=2, argrepr='', offset=48, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=50, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=3, argval='logger', argrepr='logger', offset=52, starts_line=119, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=4, argval='info', argrepr='info', offset=54, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=1, argval='Отправлено сообщение пользователю ', argrepr="'Отправлено сообщение пользователю '", offset=56, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=58, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=0, argval='DESTINATION', argrepr='DESTINATION', offset=60, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=62, starts_line=None, is_jump_target=False)
Instruction(opname='FORMAT_VALUE', opcode=155, arg=0, argval=(None, False), argrepr='', offset=64, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=2, argval=' от пользователя ', argrepr="' от пользователя '", offset=66, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=68, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=5, argval='SENDER', argrepr='SENDER', offset=70, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=72, starts_line=None, is_jump_target=False)
Instruction(opname='FORMAT_VALUE', opcode=155, arg=0, argval=(None, False), argrepr='', offset=74, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=3, argval='.', argrepr="'.'", offset=76, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_STRING', opcode=157, arg=5, argval=5, argrepr='', offset=78, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=80, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=82, starts_line=None, is_jump_target=False)
Instruction(opname='JUMP_FORWARD', opcode=110, arg=60, argval=146, argrepr='to 146', offset=84, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=86, starts_line=120, is_jump_target=True)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=0, argval='DESTINATION', argrepr='DESTINATION', offset=88, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=90, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=92, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=1, argval='names', argrepr='names', offset=94, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=96, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=124, argval=124, argrepr='', offset=98, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=100, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=1, argval='names', argrepr='names', offset=102, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=104, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=0, argval='DESTINATION', argrepr='DESTINATION', offset=106, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=108, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=110, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=2, argval='listen_socks', argrepr='listen_socks', offset=112, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=7, argval='not in', argrepr='not in', offset=114, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=124, argval=124, argrepr='', offset=116, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=6, argval='ConnectionError', argrepr='ConnectionError', offset=118, starts_line=121, is_jump_target=False)
Instruction(opname='RAISE_VARARGS', opcode=130, arg=1, argval=1, argrepr='', offset=120, starts_line=None, is_jump_target=False)
Instruction(opname='JUMP_FORWARD', opcode=110, arg=22, argval=146, argrepr='to 146', offset=122, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=3, argval='logger', argrepr='logger', offset=124, starts_line=123, is_jump_target=True)
Instruction(opname='LOAD_METHOD', opcode=160, arg=7, argval='error', argrepr='error', offset=126, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=4, argval='Пользователь ', argrepr="'Пользователь '", offset=128, starts_line=124, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=130, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=0, argval='DESTINATION', argrepr='DESTINATION', offset=132, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=134, starts_line=None, is_jump_target=False)
Instruction(opname='FORMAT_VALUE', opcode=155, arg=0, argval=(None, False), argrepr='', offset=136, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=5, argval=' не зарегистрирован на сервере, отправка сообщения невозможна.', argrepr="' не зарегистрирован на сервере, отправка сообщения невозможна.'", offset=138, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_STRING', opcode=157, arg=3, argval=3, argrepr='', offset=140, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=142, starts_line=123, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=144, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=0, argval=None, argrepr='None', offset=146, starts_line=None, is_jump_target=True)
Instruction(opname='RETURN_VALUE', opcode=83, arg=None, argval=None, argrepr='', offset=148, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=0, argval='logger', argrepr='logger', offset=0, starts_line=129, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=1, argval='debug', argrepr='debug', offset=2, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=1, argval='Разбор сообщения от клиента : ', argrepr="'Разбор сообщения от клиента : '", offset=4, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=6, starts_line=None, is_jump_target=False)
Instruction(opname='FORMAT_VALUE', opcode=155, arg=0, argval=(None, False), argrepr='', offset=8, starts_line=None, is_jump_target=False)
Instruction(opname='BUILD_STRING', opcode=157, arg=2, argval=2, argrepr='', offset=10, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=12, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=14, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=2, argval='ACTION', argrepr='ACTION', offset=16, starts_line=131, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=18, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=20, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=186, argval=186, argrepr='', offset=22, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=24, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=2, argval='ACTION', argrepr='ACTION', offset=26, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=28, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=3, argval='PRESENCE', argrepr='PRESENCE', offset=30, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=2, argval='==', argrepr='==', offset=32, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=186, argval=186, argrepr='', offset=34, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=4, argval='TIME', argrepr='TIME', offset=36, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=38, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=40, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=186, argval=186, argrepr='', offset=42, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=5, argval='USER', argrepr='USER', offset=44, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=46, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=48, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=186, argval=186, argrepr='', offset=50, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=52, starts_line=133, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=5, argval='USER', argrepr='USER', offset=54, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=56, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=6, argval='ACCOUNT_NAME', argrepr='ACCOUNT_NAME', offset=58, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=60, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=62, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=7, argval='names', argrepr='names', offset=64, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=8, argval='keys', argrepr='keys', offset=66, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=0, argval=0, argrepr='', offset=68, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=7, argval='not in', argrepr='not in', offset=70, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=140, argval=140, argrepr='', offset=72, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=2, argval='client', argrepr='client', offset=74, starts_line=134, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=76, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=7, argval='names', argrepr='names', offset=78, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=80, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=5, argval='USER', argrepr='USER', offset=82, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=84, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=6, argval='ACCOUNT_NAME', argrepr='ACCOUNT_NAME', offset=86, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=88, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_SUBSCR', opcode=60, arg=None, argval=None, argrepr='', offset=90, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=2, argval='client', argrepr='client', offset=92, starts_line=135, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=9, argval='getpeername', argrepr='getpeername', offset=94, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=0, argval=0, argrepr='', offset=96, starts_line=None, is_jump_target=False)
Instruction(opname='UNPACK_SEQUENCE', opcode=92, arg=2, argval=2, argrepr='', offset=98, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_FAST', opcode=125, arg=3, argval='client_ip', argrepr='client_ip', offset=100, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_FAST', opcode=125, arg=4, argval='client_port', argrepr='client_port', offset=102, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=104, starts_line=136, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=10, argval='database', argrepr='database', offset=106, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=11, argval='user_login', argrepr='user_login', offset=108, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=110, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=5, argval='USER', argrepr='USER', offset=112, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=114, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=6, argval='ACCOUNT_NAME', argrepr='ACCOUNT_NAME', offset=116, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=118, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=3, argval='client_ip', argrepr='client_ip', offset=120, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=4, argval='client_port', argrepr='client_port', offset=122, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=3, argval=3, argrepr='', offset=124, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=126, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=12, argval='send_message', argrepr='send_message', offset=128, starts_line=137, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=2, argval='client', argrepr='client', offset=130, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=13, argval='RESPONSE_200', argrepr='RESPONSE_200', offset=132, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_FUNCTION', opcode=131, arg=2, argval=2, argrepr='', offset=134, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=136, starts_line=None, is_jump_target=False)
Instruction(opname='JUMP_FORWARD', opcode=110, arg=42, argval=182, argrepr='to 182', offset=138, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=14, argval='RESPONSE_400', argrepr='RESPONSE_400', offset=140, starts_line=139, is_jump_target=True)
Instruction(opname='STORE_FAST', opcode=125, arg=5, argval='response', argrepr='response', offset=142, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=2, argval='Имя пользователя уже занято.', argrepr="'Имя пользователя уже занято.'", offset=144, starts_line=140, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=5, argval='response', argrepr='response', offset=146, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=15, argval='ERROR', argrepr='ERROR', offset=148, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_SUBSCR', opcode=60, arg=None, argval=None, argrepr='', offset=150, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=12, argval='send_message', argrepr='send_message', offset=152, starts_line=141, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=2, argval='client', argrepr='client', offset=154, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=5, argval='response', argrepr='response', offset=156, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_FUNCTION', opcode=131, arg=2, argval=2, argrepr='', offset=158, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=160, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=162, starts_line=142, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=16, argval='clients', argrepr='clients', offset=164, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=17, argval='remove', argrepr='remove', offset=166, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=2, argval='client', argrepr='client', offset=168, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=170, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=172, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=2, argval='client', argrepr='client', offset=174, starts_line=143, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=18, argval='close', argrepr='close', offset=176, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=0, argval=0, argrepr='', offset=178, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=180, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=0, argval=None, argrepr='None', offset=182, starts_line=144, is_jump_target=True)
Instruction(opname='RETURN_VALUE', opcode=83, arg=None, argval=None, argrepr='', offset=184, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=2, argval='ACTION', argrepr='ACTION', offset=186, starts_line=146, is_jump_target=True)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=188, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=190, starts_line=None, is_jump_target=False)
Instruction(opname='EXTENDED_ARG', opcode=144, arg=1, argval=1, argrepr='', offset=192, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=266, argval=266, argrepr='', offset=194, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=196, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=2, argval='ACTION', argrepr='ACTION', offset=198, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=200, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=19, argval='MESSAGE', argrepr='MESSAGE', offset=202, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=2, argval='==', argrepr='==', offset=204, starts_line=None, is_jump_target=False)
Instruction(opname='EXTENDED_ARG', opcode=144, arg=1, argval=1, argrepr='', offset=206, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=266, argval=266, argrepr='', offset=208, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=20, argval='DESTINATION', argrepr='DESTINATION', offset=210, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=212, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=214, starts_line=None, is_jump_target=False)
Instruction(opname='EXTENDED_ARG', opcode=144, arg=1, argval=1, argrepr='', offset=216, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=266, argval=266, argrepr='', offset=218, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=4, argval='TIME', argrepr='TIME', offset=220, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=222, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=224, starts_line=None, is_jump_target=False)
Instruction(opname='EXTENDED_ARG', opcode=144, arg=1, argval=1, argrepr='', offset=226, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=266, argval=266, argrepr='', offset=228, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=21, argval='SENDER', argrepr='SENDER', offset=230, starts_line=147, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=232, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=234, starts_line=None, is_jump_target=False)
Instruction(opname='EXTENDED_ARG', opcode=144, arg=1, argval=1, argrepr='', offset=236, starts_line=146, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=266, argval=266, argrepr='', offset=238, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=22, argval='MESSAGE_TEXT', argrepr='MESSAGE_TEXT', offset=240, starts_line=147, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=242, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=244, starts_line=None, is_jump_target=False)
Instruction(opname='EXTENDED_ARG', opcode=144, arg=1, argval=1, argrepr='', offset=246, starts_line=146, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=266, argval=266, argrepr='', offset=248, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=250, starts_line=148, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=23, argval='messages', argrepr='messages', offset=252, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=24, argval='append', argrepr='append', offset=254, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=256, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=258, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=260, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=0, argval=None, argrepr='None', offset=262, starts_line=149, is_jump_target=False)
Instruction(opname='RETURN_VALUE', opcode=83, arg=None, argval=None, argrepr='', offset=264, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=2, argval='ACTION', argrepr='ACTION', offset=266, starts_line=151, is_jump_target=True)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=268, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=270, starts_line=None, is_jump_target=False)
Instruction(opname='EXTENDED_ARG', opcode=144, arg=1, argval=1, argrepr='', offset=272, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=372, argval=372, argrepr='', offset=274, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=276, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=2, argval='ACTION', argrepr='ACTION', offset=278, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=280, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=25, argval='EXIT', argrepr='EXIT', offset=282, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=2, argval='==', argrepr='==', offset=284, starts_line=None, is_jump_target=False)
Instruction(opname='EXTENDED_ARG', opcode=144, arg=1, argval=1, argrepr='', offset=286, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=372, argval=372, argrepr='', offset=288, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=6, argval='ACCOUNT_NAME', argrepr='ACCOUNT_NAME', offset=290, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=292, starts_line=None, is_jump_target=False)
Instruction(opname='COMPARE_OP', opcode=107, arg=6, argval='in', argrepr='in', offset=294, starts_line=None, is_jump_target=False)
Instruction(opname='EXTENDED_ARG', opcode=144, arg=1, argval=1, argrepr='', offset=296, starts_line=None, is_jump_target=False)
Instruction(opname='POP_JUMP_IF_FALSE', opcode=114, arg=372, argval=372, argrepr='', offset=298, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=300, starts_line=152, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=10, argval='database', argrepr='database', offset=302, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=26, argval='user_logout', argrepr='user_logout', offset=304, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=306, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=6, argval='ACCOUNT_NAME', argrepr='ACCOUNT_NAME', offset=308, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=310, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=312, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=314, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=316, starts_line=153, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=16, argval='clients', argrepr='clients', offset=318, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=17, argval='remove', argrepr='remove', offset=320, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=322, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=7, argval='names', argrepr='names', offset=324, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=326, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=6, argval='ACCOUNT_NAME', argrepr='ACCOUNT_NAME', offset=328, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=330, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=332, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=1, argval=1, argrepr='', offset=334, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=336, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=338, starts_line=154, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=7, argval='names', argrepr='names', offset=340, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=342, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=6, argval='ACCOUNT_NAME', argrepr='ACCOUNT_NAME', offset=344, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=346, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=348, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_METHOD', opcode=160, arg=18, argval='close', argrepr='close', offset=350, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_METHOD', opcode=161, arg=0, argval=0, argrepr='', offset=352, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=354, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=0, argval='self', argrepr='self', offset=356, starts_line=155, is_jump_target=False)
Instruction(opname='LOAD_ATTR', opcode=106, arg=7, argval='names', argrepr='names', offset=358, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=1, argval='message', argrepr='message', offset=360, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=6, argval='ACCOUNT_NAME', argrepr='ACCOUNT_NAME', offset=362, starts_line=None, is_jump_target=False)
Instruction(opname='BINARY_SUBSCR', opcode=25, arg=None, argval=None, argrepr='', offset=364, starts_line=None, is_jump_target=False)
Instruction(opname='DELETE_SUBSCR', opcode=61, arg=None, argval=None, argrepr='', offset=366, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=0, argval=None, argrepr='None', offset=368, starts_line=156, is_jump_target=False)
Instruction(opname='RETURN_VALUE', opcode=83, arg=None, argval=None, argrepr='', offset=370, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=14, argval='RESPONSE_400', argrepr='RESPONSE_400', offset=372, starts_line=159, is_jump_target=True)
Instruction(opname='STORE_FAST', opcode=125, arg=5, argval='response', argrepr='response', offset=374, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=3, argval='Запрос некорректен.', argrepr="'Запрос некорректен.'", offset=376, starts_line=160, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=5, argval='response', argrepr='response', offset=378, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=15, argval='ERROR', argrepr='ERROR', offset=380, starts_line=None, is_jump_target=False)
Instruction(opname='STORE_SUBSCR', opcode=60, arg=None, argval=None, argrepr='', offset=382, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_GLOBAL', opcode=116, arg=12, argval='send_message', argrepr='send_message', offset=384, starts_line=161, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=2, argval='client', argrepr='client', offset=386, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_FAST', opcode=124, arg=5, argval='response', argrepr='response', offset=388, starts_line=None, is_jump_target=False)
Instruction(opname='CALL_FUNCTION', opcode=131, arg=2, argval=2, argrepr='', offset=390, starts_line=None, is_jump_target=False)
Instruction(opname='POP_TOP', opcode=1, arg=None, argval=None, argrepr='', offset=392, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=0, argval=None, argrepr='None', offset=394, starts_line=162, is_jump_target=False)
Instruction(opname='RETURN_VALUE', opcode=83, arg=None, argval=None, argrepr='', offset=396, starts_line=None, is_jump_target=False)
Instruction(opname='LOAD_CONST', opcode=100, arg=0, argval=None, argrepr='None', offset=398, starts_line=None, is_jump_target=False)
Instruction(opname='RETURN_VALUE', opcode=83, arg=None, argval=None, argrepr='', offset=400, starts_line=None, is_jump_target=False)
['dict', 'super', 'logger', 'socket', 'OSError', 'select', 'get_message', 'DESTINATION', 'send_message', 'SENDER', 'ConnectionError', 'ACTION', 'PRESENCE', 'TIME', 'USER', 'ACCOUNT_NAME', 'RESPONSE_200', 'RESPONSE_400', 'ERROR', 'MESSAGE', 'MESSAGE_TEXT', 'EXIT']

Process finished with exit code 1
"""