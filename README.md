# Configurador E95-DTU

Programa de escritorio para configurar y probar el radio E95-DTU(900SL22-485) y E95-DTU(900SL30-485) en Linux. Reemplaza la configuración local del software oficial de Ebyte, que no funciona bien en este sistema.

La interfaz está hecha con PyQt6 y habla con el radio por el puerto serie.

## Qué hace

- **Configuración.** Lee y graba los registros `00H`–`08H` (dirección, red, velocidad, paridad, potencia, canal, clave y el resto de opciones). También guarda y carga esos parámetros en un archivo JSON. El canal inicia en 915.125 MHz y, junto al número, se muestra la frecuencia.
- **Enlace.** Envía texto o hexadecimal para probar una conexión, con CRC16 Modbus opcional. El modo ping-pong manda `ping` y, si otro equipo tiene el mismo programa abierto, responde `pong`.
- **Ayuda.** Muestra la conexión, las partes del radio, los modos de trabajo y la fórmula de frecuencia.
- **Configuración.** Permite habilitar cualquier canal, incluso los de 915 MHz o menos. Sin esa opción solo se pueden elegir frecuencias mayores a 915 MHz.

Las pestañas Configuración y Enlace comparten el puerto: si ya está abierto, se puede cambiar de pestaña sin volver a abrirlo.

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

## Uso del radio

Para leer o grabar parámetros, el radio tiene que estar en modo configuración: indicador M1 encendido y M0 apagado. En ese modo el puerto de la PC queda en 9600 8N1, aunque la velocidad guardada en el módulo sea otra.

Para enviar datos o usar el ping-pong, el radio tiene que estar en modo transparente: M0 y M1 apagados. La velocidad y la paridad del puerto tienen que coincidir con las del radio. El botón **Copiar de la configuración** las toma del formulario.

## Licencia

Copyright (C) 2026 Zamper.io

El código de este programa se distribuye bajo la licencia [GPL-3.0](LICENSE).

Los manuales de Ebyte, sus figuras y el ejecutable original quedan fuera de este repositorio.

## Pruebas

```bash
.venv/bin/python -m unittest discover -s tests -v
```
