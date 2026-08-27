# Control Flota — cierre de Fase 1

## Alcance aplicado

La Fase 1 reutiliza los modelos, vistas y URLs existentes para transportes,
conductores, camiones, tarifas globales y rutas. No incorpora modelos,
migraciones ni reasignaciones de datos históricos.

La autorización del perfil `CONTROL_FLOTA` se basa en `PERFIL_USUARIO`,
`PERMISO`, empresa activa y `USERS_EMPRESA`. `USERS_EXTENSION` continúa
siendo compatible con perfiles legados, pero no es obligatorio para un
usuario interno autorizado mediante el sistema de perfiles.

## Situación histórica de Transporte en SBH

La revisión de datos de cierre confirmó:

- SBH no tiene transportistas habilitados propios en `SOCIONEGOCIO`.
- 1.101 camiones SBH referencian transportistas registrados bajo Terramar.
- 1.198 conductores SBH referencian transportistas registrados bajo Terramar.
- 623 tarifas SBH referencian transportistas registrados bajo Terramar.

Estos datos no se duplicaron, migraron ni reasignaron durante la Fase 1.
Por esta razón, la pantalla Transporte de SBH puede permanecer vacía aunque
los demás módulos de flota tengan datos.

## Decisión pendiente antes de modificar datos

Antes de cualquier corrección histórica debe definirse explícitamente una de
estas alternativas:

1. Maestro Transporte compartido entre empresas.
2. Maestro Transporte independiente por empresa.

Esta decisión debe investigarse considerando planificación, tarifas,
citaciones, proformas e integraciones SAP. No forma parte de la Fase 1 y no se
ha iniciado la Fase 2.

## Tarifas Globales

Tarifas Globales se mantiene disponible para SBH. La base real contiene 565
tarifas SBH habilitadas y 1.210 citaciones SBH con tarifa asociada, por lo que
el módulo forma parte del uso vigente de esa empresa.
