# Registro de usuarios

## Generales

El registro es abierto y se espera un alto flujo los primeros días de funcionamiento, el apoderado puede guardar la informacion.
Se debiese registrar los pasos (paso1 - timestamp,paso2 - timestamp, etc)
El apoderado es quien se registra, se requieren los datos: nombres, correo validado, telefono celular (preferencialmente c/whatsapp), cantidad de alumnos
Para cada alumno se requiere: nombres, apellidos, curso, edad, comentarios, id-nfc-tag*, qr_string* (random passphrase). * indica que es informacion oculta para el apoderado.
Cada curso disponible es un setting general con un arreglo de strings

## Paso 1

* Logo Sistema/Colegio
* Texto explicativo (maximo 100 palabras)
* Nombres, Apellidos
* Correo Electronico, Telefono.
* Botones de accion con "Cantidad Alumnos"

Botones de accion:
1, 2, 3, 4+

## Paso 2

* Texto explicativo
Se repite segun "Cantidad Alumnos"
* Nombre Completo
* Curso, Edad
* Comentario

## Paso 3

* Texto explicativo
* Opciones de Configuración
* Opciones de Notificación

## Paso 4

Resumen de Pasos 1..3
Links para volver al paso 1, 2
Si seleccionó 4+, texto indicando el lugar donde se puede administrar.
Link a Settings para cambiar opciones.
