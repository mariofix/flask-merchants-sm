# Asignar Tag a un Alumno

Cada alumno puede tener un **tag** (código de identificación) que le permite ser reconocido en el punto de venta del casino. Este tag puede ser un código QR imprimible o un tag NFC físico.

!!! info "Acceso requerido"
    Solo usuarios con rol **Admin** pueden editar alumnos. Acceda en: `Admin → Usuarios y Roles → Alumno`

---

## ¿Qué es el Tag?

El tag es un identificador único de 8 caracteres alfanuméricos que se almacena en la ficha del alumno. Se usa para identificar al alumno en el sistema del casino al momento de registrar un almuerzo o compra en el kiosko.

El mismo tag puede representar:

- Un **código QR** imprimible (para que el alumno lo muestre con su celular o en una tarjeta).
- Un **tag NFC** físico (pulsera, tarjeta, llavero), cuyo número de serie queda asociado al alumno.

---

## Acceder al Formulario de Edición del Alumno

1. Acceda al panel administrativo (`/data-manager`).
2. Vaya a **Usuarios y Roles → Alumno**.
3. Busque el alumno en la lista y haga clic en el ícono de edición (lápiz).
4. El formulario de edición se abrirá con el campo **Tag** visible en la parte superior.

---

## Métodos para Asignar el Tag

El campo **Tag** tiene tres botones asociados:

=== "Generar QR (automático)"
    1. Haga clic en el botón verde **Generar QR**.
    2. El sistema genera automáticamente un código único de 8 caracteres (formato similar a un ID de YouTube).
    3. El campo Tag se completa con el código generado y muestra validación verde.
    4. Haga clic en **Guardar** para confirmar el cambio.

    !!! tip "Impresión del QR"
        Una vez guardado, el código QR aparece visualizado en la lista de alumnos. Puede tomar captura de pantalla o usar la vista de detalle para imprimir la tarjeta del alumno.

=== "Escanear NFC (físico)"
    1. Use un dispositivo Android con **Chrome** (el único navegador compatible con la API NFC web).
    2. En el formulario de edición del alumno, haga clic en el botón azul **📡 Escanear**.
    3. El botón mostrará **"Acerque TAG..."** y el spinner se activará.
    4. Acerque el tag NFC físico (pulsera, tarjeta, llavero) al lector NFC del dispositivo.
    5. El número de serie del tag se leerá automáticamente y se completará en el campo Tag.
    6. Haga clic en **Guardar** para confirmar.

    !!! warning "Compatibilidad NFC"
        La lectura NFC solo funciona en **Google Chrome sobre Android**. No es compatible con iOS ni con navegadores de escritorio.

=== "Entrada manual"
    1. Haga clic sobre el campo **Tag** para habilitarlo (el campo es de solo lectura por defecto).
    2. Escriba o pegue el código directamente.
    3. Haga clic en **Guardar**.

    Use esta opción para ingresar el número de serie de un tag NFC que ya leyó con otro dispositivo, o para restaurar un tag conocido.

---

## Visualización del Tag en la Lista

En la vista de lista de alumnos, la columna **Tag** muestra:

- Un **código QR** pequeño generado a partir del tag almacenado.
- El código en texto monoespaciado debajo del QR.

Si el alumno aún no tiene tag asignado, la columna aparecerá vacía.

---

## Preguntas frecuentes

??? question "¿Puedo reasignar el tag de un alumno a otro?"
    No directamente. Cada tag debe ser único. Si necesita reasignar, primero borre el tag del alumno actual y luego asígnelo al otro.

??? question "¿Qué pasa si el alumno pierde su tag NFC?"
    Puede generar un nuevo QR o escanear un nuevo tag NFC y guardar el cambio. El tag anterior dejará de funcionar en el sistema automáticamente.

??? question "¿El QR es compatible con los lectores del casino?"
    Sí. Los terminales del casino leen el mismo código que aparece en el QR. Puede imprimir el QR o mostrarlo desde la pantalla del celular.

??? question "¿Puede un alumno compartir su tag con otro alumno?"
    Solo si el apoderado del alumno tiene activada la opción **Tag compartido** en sus ajustes de cuenta. Si no, el tag es personal e intransferible.
