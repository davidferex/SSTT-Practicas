# coding=utf-8
#!/usr/bin/env python3

import socket
import selectors    #https://docs.python.org/3/library/selectors.html
import select
import types        # Para definir el tipo de datos data
import argparse     # Leer parametros de ejecución
import os           # Obtener ruta y extension
from datetime import datetime, timedelta # Fechas de los mensajes HTTP
import time         # Timeout conexión
import sys          # sys.exit
import re           # Analizador sintáctico
import logging      # Para imprimir logs



BUFSIZE = 8192 # Tamaño máximo del buffer que se puede utilizar
TIMEOUT_CONNECTION = 20 # Timout para la conexión persistente
MAX_ACCESOS = 10

# Extensiones admitidas (extension, name in HTTP)
filetypes = {"gif":"image/gif", "jpg":"image/jpg", "jpeg":"image/jpeg", "png":"image/png", "htm":"text/htm", 
             "html":"text/html", "css":"text/css", "js":"text/js"}

# Configuración de logging
logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s.%(msecs)03d] [%(levelname)-7s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger()

codigos = {200: "200 OK", 400: "400 Bad Request", 403: "403 Forbidden", 404: "404 Not Found" , 405: "405 Method Not Allowed", 408: "408 Timeout Exceeded", 505: "505 Version Not Supported"}
error1 = "<html>\n<head>\n<title>Servidor Simple para Servicios Telem&acute;ticos</title>\n</head>\n<body bgcolor=\"lightgray\">\n<h1>"
error2 = "</h1>\n<A HREF=/index.html> Volver a la pagina principal </A></body>\n</html>"


def enviar_mensaje(cs, data):
    """ Esta función envía datos (data) a través del socket cs
        Devuelve el número de bytes enviados.
    """
    i = 0
    enviados =cs.send(data[i:min(i+BUFSIZE, len(data))])
    i = i + enviados
    while i < len(data) and enviados > 0:
        enviados =cs.send(data[i:min(i+BUFSIZE, len(data))])
        i = i + enviados
    return i
    


def recibir_mensaje(cs):
    """ Esta función recibe datos a través del socket cs
        Leemos la información que nos llega. recv() devuelve un string con los datos.
    """
    datos = ""
    s = cs.recv(BUFSIZE)
    datos = s.decode()
    while len(s) == BUFSIZE:
        s = cs.recv(BUFSIZE)
        datos = datos + s.decode()
    return datos


def cerrar_conexion(cs):
    """ Esta función cierra una conexión activa.
    """
    cs.close()


def process_cookies(cookies):
    """ Esta función procesa la cookie cookie_counter
        1. Se analizan las cabeceras en headers para buscar la cabecera Cookie
        2. Una vez encontrada una cabecera Cookie se comprueba si el valor es cookie_counter
        3. Si no se encuentra cookie_counter , se devuelve 1
        4. Si se encuentra y tiene el valor MAX_ACCESSOS se devuelve MAX_ACCESOS
        5. Si se encuentra y tiene un valor 1 <= x < MAX_ACCESOS se incrementa en 1 y se devuelve el valor
    """
    counter = r'cookie_counter=(\d+)'
    er_counter = re.compile(counter)
    res = er_counter.match(cookies)
    if not res:
        return -1
    cookie_counter = int(res.group(1))
    if cookie_counter == MAX_ACCESOS:
        return MAX_ACCESOS
    elif 1 <= cookie_counter and cookie_counter < MAX_ACCESOS:
        return cookie_counter+1
    else:
        return 1




def crear_respuesta(ruta, cookie_counter, cs):
    extension = ruta.split(".")
    fichero = open(ruta, "rb")
    respuesta = "HTTP/1.1 200 OK \r\n"
    fecha = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
    respuesta = respuesta + "Date: " + fecha + "\r\n"
    respuesta = respuesta + "Server: web.elplan49.org\r\n"
    respuesta = respuesta + "Set-Cookie: cookie_counter=" + str(cookie_counter) + "; Max-Age=120;\r\n"
    respuesta = respuesta + "Content-Type: "
    respuesta = respuesta + filetypes[extension[len(extension)- 1]] + "\r\n"
    respuesta = respuesta + "Content-Length: "
    respuesta = respuesta + str(os.stat(ruta).st_size) + "\r\n"
    respuesta = respuesta + "Connection: Keep-Alive\r\n"
    respuesta = respuesta + "Keep-Alive: timeout=" + str(TIMEOUT_CONNECTION) + "\r\n"
    respuesta = respuesta + "\r\n"
    respuesta = respuesta.encode()
    datos = fichero.read(BUFSIZE)
    while datos:
        respuesta = respuesta + datos
        datos = fichero.read(BUFSIZE)
    fichero.close()
    return respuesta


def crear_error(error, cookie_counter):
    respuesta = "HTTP/1.1 " + codigos[error] + "\r\n"
    mensaje = error1 + codigos[error] + error2
    fecha = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
    respuesta = respuesta + "Date: " + fecha + "\r\n"
    respuesta = respuesta + "Server: web.elplan49.org\r\n"
    #respuesta = respuesta + "Set-Cookie: cookie_counter=" + str(cookie_counter) + "; Max-Age=120;\r\n"
    respuesta = respuesta + "Content-Type: "
    respuesta = respuesta + filetypes["html"] + "\r\n"
    respuesta = respuesta + "Content-Length: "
    respuesta = respuesta + str(len(mensaje)) + "\r\n"
    if error == 408:
        respuesta = respuesta + "Connection: Close\r\n"
    else:
        respuesta = respuesta + "Connection: Keep-Alive\r\n"
        respuesta = respuesta + "Keep-Alive: timeout=" + str(TIMEOUT_CONNECTION) + "\r\n"
    respuesta = respuesta + "\r\n"
    respuesta = respuesta.encode()
    respuesta = respuesta + mensaje.encode()
    return respuesta
    





def process_web_request(cs, webroot):
    """ Procesamiento principal de los mensajes recibidos.
        Típicamente se seguirá un procedimiento similar al siguiente (aunque el alumno puede modificarlo si lo desea)

        * Bucle para esperar hasta que lleguen datos en la red a través del socket cs con select()

            * Se comprueba si hay que cerrar la conexión por exceder TIMEOUT_CONNECTION segundos
              sin recibir ningún mensaje o hay datos. Se utiliza select.select

            * Si no es por timeout y hay datos en el socket cs.
                * Leer los datos con recv.
                * Analizar que la línea de solicitud y comprobar está bien formateada según HTTP 1.1
                    * Devuelve una lista con los atributos de las cabeceras.
                    * Comprobar si la versión de HTTP es 1.1
                    * Comprobar si es un método GET. Si no devolver un error Error 405 "Method Not Allowed".
                    * Leer URL y eliminar parámetros si los hubiera
                    * Comprobar si el recurso solicitado es /, En ese caso el recurso es index.html
                    * Construir la ruta absoluta del recurso (webroot + recurso solicitado)
                    * Comprobar que el recurso (fichero) existe, si no devolver Error 404 "Not found"
                    * Analizar las cabeceras. Imprimir cada cabecera y su valor. Si la cabecera es Cookie comprobar
                      el valor de cookie_counter para ver si ha llegado a MAX_ACCESOS.
                      Si se ha llegado a MAX_ACCESOS devolver un Error "403 Forbidden"
                    * Obtener el tamaño del recurso en bytes.
                    * Extraer extensión para obtener el tipo de archivo. Necesario para la cabecera Content-Type
                    * Preparar respuesta con código 200. Construir una respuesta que incluya: la línea de respuesta y
                      las cabeceras Date, Server, Connection, Set-Cookie (para la cookie cookie_counter),
                      Content-Length y Content-Type.
                    * Leer y enviar el contenido del fichero a retornar en el cuerpo de la respuesta.
                    * Se abre el fichero en modo lectura y modo binario
                        * Se lee el fichero en bloques de BUFSIZE bytes (8KB)
                        * Cuando ya no hay más información para leer, se corta el bucle

            * Si es por timeout, se cierra el socket tras el período de persistencia.
                * NOTA: Si hay algún error, enviar una respuesta de error con una pequeña página HTML que informe del error.
    """
    try:
        cookie_counter = 1
        while True:
            host = False
            (lista1, lista2, lista3) = select.select([cs], [],[], TIMEOUT_CONNECTION)
            if len(lista1) == 0:
                print("HOLA")
                mensaje = crear_error(408, cookie_counter)
                enviar_mensaje(cs, mensaje)
                #cerrar conexion
                break
            else:
                datos = recibir_mensaje(lista1[0])
                print(datos)
                primera_linea = r'(.+) (/.*) HTTP/(.*)\r\n' 
                mensaje_completo = r'(.+\r\n)+\r\n'
                er_primera = re.compile(primera_linea)
                res = er_primera.match(datos)
                if not res:
                    mensaje = crear_error(400, cookie_counter)
                    enviar_mensaje(cs, mensaje)
                    continue
                linea1 = datos[res.start():res.end()]
                metodo = res.group(1)
                if metodo != "GET":
                    mensaje = crear_error(405, cookie_counter)
                    enviar_mensaje(cs, mensaje)
                    continue
                if res.group(3) != "1.1":
                    mensaje = crear_error(505, cookie_counter)
                    enviar_mensaje(cs, mensaje)
                    continue               
                url = res.group(2)
                if url == "/":
                    #tratar
                    #devolver index.html
                    url = "/index.html"
                #Para eliminar los parametros.
                url = url.split('?')
                ruta = webroot+url[0]
                if not os.path.isfile(ruta):
                    mensaje = crear_error(404, cookie_counter)
                    enviar_mensaje(cs, mensaje)
                    continue
                er_mensaje_completo = re.compile(mensaje_completo)
                res = er_mensaje_completo.match(datos)
                if not res:
                    mensaje = crear_error(400, cookie_counter)
                    enviar_mensaje(cs, mensaje)
                    continue
                i = 1
                datos = datos.split("\n")
                lineas = r'([a-zA-Z\-]+):'
                er_cabecera = re.compile(lineas)
                while datos[i] != "\r":
                    res = er_cabecera.match(datos[i])
                    if res:
                        atributos = datos[i][res.end()+1:len(datos[i]) - 1]
                        cabecera = datos[i][res.start():res.end()]
                        if cabecera == "Host:":
                            host = True
                        if cabecera == "Cookie:":
                            cookie_counter = process_cookies(atributos)
                            if cookie_counter == -1:
                                mensaje = crear_error(400, cookie_counter)
                                enviar_mensaje(cs, mensaje)
                    i = i + 1
                if not host:
                    mensaje = crear_error(400, cookie_counter)
                    enviar_mensaje(cs, mensaje)
                elif cookie_counter == MAX_ACCESOS:
                    mensaje = crear_error(403, cookie_counter)
                    enviar_mensaje(cs, mensaje)
                else:
                    respuesta = crear_respuesta(ruta, cookie_counter, cs)
                    enviar_mensaje(cs, respuesta)
    except ConnectionError:
        print("ConnectionError")
    finally:
        cerrar_conexion(cs)

def main():
    """ Función principal del servidor
    """

    try:

        # Argument parser para obtener la ip y puerto de los parámetros de ejecución del programa. IP por defecto 0.0.0.0
        parser = argparse.ArgumentParser()
        parser.add_argument("-p", "--port", help="Puerto del servidor", type=int, required=True)
        parser.add_argument("-ip", "--host", help="Dirección IP del servidor o localhost", required=True)
        parser.add_argument("-wb", "--webroot", help="Directorio base desde donde se sirven los ficheros (p.ej. /home/user/mi_web)")
        parser.add_argument('--verbose', '-v', action='store_true', help='Incluir mensajes de depuración en la salida')
        args = parser.parse_args()


        if args.verbose:
            logger.setLevel(logging.DEBUG)

        logger.info('Enabling server in address {} and port {}.'.format(args.host, args.port))

        logger.info("Serving files from {}".format(args.webroot))



        """ Funcionalidad a realizar
        * Crea un socket TCP (SOCK_STREAM)
        * Permite reusar la misma dirección previamente vinculada a otro proceso. Debe ir antes de sock.bind
        * Vinculamos el socket a una IP y puerto elegidos

        * Escucha conexiones entrantes

        * Bucle infinito para mantener el servidor activo indefinidamente
            - Aceptamos la conexión

            - Creamos un proceso hijo

            - Si es el proceso hijo se cierra el socket del padre y procesar la petición con process_web_request()

            - Si es el proceso padre cerrar el socket que gestiona el hijo.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((args.host, args.port))
        s.listen()
        while True:
            (conn, addr) = s.accept()
            pid = os.fork()
            if (pid == 0):
                s.close()
                process_web_request(conn, args.webroot)
                os._exit(0)
            else:
                conn.close()
        


    except KeyboardInterrupt:
        True

if __name__== "__main__":
    main()
