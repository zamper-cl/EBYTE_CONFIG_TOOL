# Configurador E95-DTU y E860-DTU

Programa de escritorio para configurar el radio E95-DTU(900SL22-485), el E95-DTU(900SL30-485) y el interruptor inalámbrico E860-DTU(X0X0-900SLxx)-V2 en Linux. Reemplaza la configuración local del software oficial de Ebyte, que no funciona bien en este sistema.

Al abrir pregunta qué equipo se va a usar. La interfaz está hecha con PyQt6 y habla con el equipo por el puerto serie.

## Qué hace

- **E95, configuración.** Lee y graba los registros `00H`–`08H` (dirección, red, velocidad, paridad, potencia, canal, clave y el resto de opciones). También guarda y carga esos parámetros en un archivo JSON. El canal inicia en 915.125 MHz y, junto al número, se muestra la frecuencia.
- **E95, enlace.** Envía texto o hexadecimal para probar una conexión, con CRC16 Modbus opcional. El modo ping-pong manda `ping` y, si otro equipo tiene el mismo programa abierto, responde `pong`.
- **E95, ayuda.** Muestra la conexión, las partes del radio, los modos de trabajo y la fórmula de frecuencia.
- **E860.** Entra en modo AT por RS485, lee la información del equipo y graba la velocidad, el canal y la clave. El rol, el modo, la velocidad de aire y los datos de emparejamiento se muestran y no se modifican. También puede salir de AT, volver a fábrica y reiniciar. Los parámetros se guardan en un JSON aparte del E95.
- **Canales.** En los dos equipos el canal inicia en 915.125 MHz. Sin la opción de permitir cualquier canal, el selector no ofrece frecuencias de 915 MHz o menos. Esa opción es la misma para los dos.

Las pestañas Configuración y Enlace del E95 comparten el puerto: si ya está abierto, se puede cambiar de pestaña sin volver a abrirlo. El E860 no tiene enlace ni ping-pong.

## Requisitos

- Python 3.10 o posterior
- Permiso para usar el puerto serie. En Linux el usuario tiene que estar en el grupo `dialout`:

```bash
sudo usermod -aG dialout "$USER"
```

Hay que cerrar la sesión y volver a entrar para que el grupo quede activo.

## Ejecutar

Desde la raíz del proyecto:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m ebyte_dtu
```

## Uso del E95

Para leer o grabar parámetros, el radio tiene que estar en modo configuración: indicador M1 encendido y M0 apagado. En ese modo el puerto de la PC queda en 9600 8N1, aunque la velocidad guardada en el módulo sea otra.

Para enviar datos o usar el ping-pong, el radio tiene que estar en modo transparente: M0 y M1 apagados. La velocidad y la paridad del puerto tienen que coincidir con las del radio. El botón **Copiar de la configuración** las toma del formulario.

## Uso del E860

La configuración sale por RS485, no por los pines de modo del E95. El puerto de la PC abre a 115200 8N1 y se puede cambiar la velocidad para que coincida con la que ya tiene el equipo. Los bits de datos, la paridad y el bit de parada quedan en 8N1.

Hay que pulsar **Entrar en AT** antes de leer o grabar. Ese paso manda `AT+VER` y espera `+OK`. Las consultas van sin signo de pregunta (`AT+SN`, no `AT+SN?`). Si el equipo pide contraseña, el programa la solicita y envía `AT+PASSWORDSET`. Al grabar se envían el canal, la clave y, al final, la velocidad. Si esa velocidad cambió, hay que cerrar el puerto y abrirlo de nuevo con el valor nuevo.

## Licencia

Copyright (C) 2026 Zamper.io

El código de este programa se distribuye bajo la licencia [GPL-3.0](LICENSE).

Los manuales de Ebyte, sus figuras y el ejecutable original quedan fuera de este repositorio.

## Pruebas

```bash
.venv/bin/python -m unittest discover -s tests -v
```
