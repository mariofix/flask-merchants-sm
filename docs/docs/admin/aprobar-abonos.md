# Aprobar Abonos en Cafetería

Cuando un apoderado elige **Efectivo/Tarjetas** como forma de pago al abonar saldo, el abono queda en estado **Procesando** hasta que el personal del casino confirme manualmente el pago presencial. Este proceso se realiza desde el panel administrativo.

!!! info "Acceso requerido"
    Solo usuarios con rol **Admin** pueden aprobar abonos. Acceda en: `Admin → Casino → Abonos`

---

## ¿Cuándo se requiere aprobación manual?

| Forma de pago | Aprobación |
|---|---|
| **Transferencia Electrónica (Khipu)** | Automática — Khipu confirma el pago vía webhook. |
| **Efectivo / Tarjetas en Cafetería** | **Manual** — El personal debe aprobar el abono tras recibir el pago. |

Los abonos en cafetería quedan en estado **Procesando** hasta que un administrador los apruebe.

---

## Proceso de aprobación

### 1. Identificar los abonos pendientes

1. Acceda al panel administrativo (`/data-manager`).
2. Vaya a **Casino → Abonos**.
3. Filtre o busque por **Forma de pago = cafetería** y **Estado = Procesando** para localizar los abonos que esperan confirmación.

!!! tip "Dashboard de resumen"
    El panel principal del administrador muestra el número de **abonos pendientes** al ingresar al sistema, lo que permite identificar rápidamente si hay abonos por aprobar.

### 2. Aprobar el abono

1. Seleccione la casilla de verificación junto al abono (o abonos) que desea aprobar.
2. En el menú de **Acciones**, seleccione **Aprobar Abono**.
3. Confirme la acción en el cuadro de diálogo.

Al aprobar:

- El estado del pago cambia de **Procesando** a **Completado (succeeded)**.
- El monto del abono se **acredita automáticamente** al saldo de la cuenta del apoderado.
- Si el apoderado tiene activada la opción de **comprobante de transferencia**, se le envía un correo de confirmación.

!!! warning "Solo abonos en estado 'Procesando'"
    Solo se pueden aprobar abonos que estén en estado **Procesando**. Si un abono no está en ese estado, el sistema lo saltará y mostrará una advertencia.

---

## Enviar comprobante manualmente

Si necesita reenviar el comprobante de un abono ya aprobado (por ejemplo, si el apoderado no lo recibió):

1. Seleccione el abono en la lista.
2. En **Acciones**, seleccione **Enviar Comprobante**.
3. El sistema enviará un correo con los detalles del abono al apoderado y, si corresponde, al correo alternativo configurado.

---

## Información del abono en la lista

| Columna | Descripción |
|---|---|
| **Código** | Identificador único del abono (primeros 8 caracteres en mayúsculas). |
| **Apoderado** | Nombre del apoderado que realizó el abono. |
| **Monto** | Valor del abono en pesos chilenos. |
| **Forma de pago** | cafetería / khipu / otro proveedor. |
| **Descripción** | Nota interna del abono. |
| **Fecha** | Fecha y hora de creación del abono. |

---

## Preguntas frecuentes

??? question "¿Puedo aprobar varios abonos a la vez?"
    Sí. Seleccione múltiples abonos con las casillas de verificación y aplique la acción **Aprobar Abono** una sola vez. El sistema procesará cada uno y mostrará un resumen de cuántos se aprobaron.

??? question "¿Qué pasa si apruebo un abono por error?"
    El saldo ya habrá sido acreditado al apoderado. Contacte al administrador para ajustar manualmente el saldo desde la ficha del apoderado en **Admin → Usuarios y Roles → Apoderado**.

??? question "¿Se registra la aprobación en algún log?"
    Sí. Cada aprobación queda registrada en el **log de auditoría** del sistema (visible en el panel principal del administrador) con el código del abono, el apoderado, el monto y el saldo resultante.

??? question "¿Por qué un abono de Khipu aparece como 'Procesando'?"
    Los abonos de Khipu deberían confirmarse automáticamente. Si uno aparece en Procesando por más de 24 horas, puede haber un problema con el webhook de Khipu. Contacte al administrador técnico del sistema.
