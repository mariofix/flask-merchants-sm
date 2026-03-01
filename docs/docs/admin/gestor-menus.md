# Gestor de Menús

El **Gestor de Menús** es la herramienta principal para crear y programar los menús diarios del casino. Está disponible en el panel administrativo en **Menú Casino → Gestor de Menús**.

!!! info "Acceso requerido"
    Esta herramienta es accesible para usuarios con rol **Admin** o **POS**. Acceda en: `/data-manager/gestor_menu/`

---

## Requisito previo: Catálogo de Platos

Antes de crear un menú, debe existir al menos un **plato activo** en el catálogo.

Para agregar platos, acceda a **Admin → Casino → Plato → Crear** y registre cada plato con:

| Campo | Descripción |
|---|---|
| **Nombre** | Nombre del plato (ej: "Cazuela de Vacuno"). |
| **Activo** | Marque esta casilla para que el plato aparezca disponible. |
| **Vegano / Vegetariano** | Etiqueta dietética. |
| **Hipocalórico** | Etiqueta para dietas bajas en calorías. |
| **Contiene Gluten / Alérgenos** | Marca de alerta para restricciones. |

!!! warning "Sin platos, no hay menú"
    Si no hay platos activos, el formulario de creación de menú estará deshabilitado.

---

## Opción 1 — Crear Menú del Día

Use esta opción para crear un nuevo menú para una fecha específica asignando los platos de cada curso.

### Pasos

1. En el Gestor de Menús, haga clic en **Ir al formulario de creación**.
2. Complete el panel **Datos del Menú** a la izquierda:

    | Campo | Descripción |
    |---|---|
    | **Fecha** | Día del menú. El sistema sugiere mañana por defecto. Al seleccionar, se muestra el nombre del día. |
    | **Descripción** | Nombre identificador del menú (ej: "Menú del lunes especial"). **Campo obligatorio.** Se usa como identificador único (slug). |
    | **Precio (CLP)** | Precio del menú en pesos. Opcional. |
    | **Stock (raciones)** | Número máximo de almuerzos disponibles. Por defecto: 50. |

3. En el panel central, seleccione **un plato por curso**:

    | Curso | Descripción |
    |---|---|
    | **Entrada** (azul) | Sopa, ensalada, etc. |
    | **Fondo** (verde) | Plato principal. |
    | **Postre** (amarillo) | Postre o fruta. |

    Cada columna tiene un **buscador en tiempo real** para filtrar platos por nombre. Los platos muestran etiquetas dietéticas (V = Vegano, Veg = Vegetariano, Hip = Hipocalórico, ⚠ = Alérgenos).

4. Opcionalmente, seleccione una **foto** del menú en la galería inferior.
5. El panel **Resumen de selección** (lateral) muestra en tiempo real los platos elegidos.
6. Haga clic en **✅ Crear Menú del Día**.

!!! tip "Descripción única"
    La descripción del menú se convierte en un identificador único (slug). Si ya existe un menú con la misma descripción, el sistema lo avisará y no creará el duplicado.

---

## Opción 2 — Copiar Menú a Nuevas Fechas

Use esta opción para reutilizar un menú existente en uno o más días adicionales. El menú origen se clona completo, incluyendo todos sus platos.

### Pasos

1. En el Gestor de Menús, ubique el panel **② Copiar Menú a Nuevas Fechas**.
2. En el selector **Menú origen**, elija el menú que desea copiar de la lista de menús recientes.
3. En el campo **Fechas destino**, ingrese las fechas separadas por comas en formato `AAAA-MM-DD`:

    ```
    2026-03-10, 2026-03-11, 2026-03-12
    ```

4. Haga clic en **📋 Copiar Menú**.

El sistema creará una copia del menú para cada fecha indicada. Si una fecha ya tiene un menú con el mismo nombre, esa fecha será omitida y se avisará en un mensaje.

---

## Panel de Menús Recientes

La parte inferior del Gestor muestra los últimos **30 menús** con:

- Fecha y slug (identificador)
- Precio y stock disponible
- Estado activo/inactivo
- Platos asignados (entrada, fondo, postre)

---

## Preguntas frecuentes

??? question "¿Puedo editar un menú ya creado?"
    Sí. Acceda a **Admin → Casino → Menú Diario**, busque el menú y use el botón de edición. Puede cambiar precio, stock, estado activo y foto.

??? question "¿Cómo desactivo un menú para que no sea pedible?"
    Edite el menú desde **Admin → Casino → Menú Diario** y desmarque la casilla **Activo**. El menú dejará de aparecer en el calendario de pedidos.

??? question "¿La copia de menú también copia las fotos?"
    Sí. La copia clona todos los datos del menú origen, incluyendo la foto asignada y todos los platos de cada curso.
