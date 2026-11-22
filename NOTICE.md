# Aviso y atribución

Este archivo acompaña al código. No es un dictamen jurídico.

## Qué es este proyecto

Es un proyecto personal de Yann Favier (GitHub: [Yannedugo](https://github.com/Yannedugo)), sin ánimo de lucro. Ofrece una librería, un servidor MCP, una página local de prueba y una integración de Home Assistant para consultar tiempos del tranvía de Tenerife.

No es un servicio de Metropolitano de Tenerife, S.A. ni del Cabildo Insular de Tenerife. No está afiliado, patrocinado, avalado ni mantenido por esas entidades. No debe presentarse como un canal oficial.

## Marcas

«Metrotenerife», «Tranvía de Tenerife», «TITSA», «Cabildo de Tenerife» y los signos, colores y logotipos asociados pertenecen a sus titulares. Aquí se usan solo de forma nominativa, para decir de qué servicio se habla. Este repositorio no usa esos logotipos ni se presenta con su identidad corporativa.

## Datos en vivo

Los tiempos, posiciones y ocupación se leen en el momento desde la web pública TranvíaOnline (`https://tranviaonline.metrotenerife.com`), que no es una API con contrato. Este programa:

- no garantiza que los datos sean exactos, completos ni estén disponibles;
- no los almacena como un histórico para redistribuirlos;
- no republica el feed;
- sondea con caché, una petición a la vez y, en Home Assistant, un intervalo mínimo de 60 segundos.

El `User-Agent` identifica el proyecto e incluye la URL del repositorio y un contacto: los issues de GitHub.

No uses estos datos para una decisión de la que dependa la seguridad, un compromiso horario crítico o cualquier otra consecuencia importante. Contrasta con el panel oficial o con el operador.

## Catálogo derivado del GTFS

El catálogo de paradas, coordenadas, orden de marcha y minutos entre paradas consecutivas es una obra derivada del GTFS de Metropolitano de Tenerife, publicado por el Cabildo Insular de Tenerife.

- **Autor / titular de los datos de origen:** Cabildo Insular de Tenerife / Metropolitano de Tenerife.
- **Fuente:** [dataset en datos.tenerife.es](https://datos.tenerife.es/ckan/dataset/4b83e018-37d9-40a6-b6d1-1df2b91c8117) y copia en [metrotenerife.com/transit/google_transit.zip](https://metrotenerife.com/transit/google_transit.zip).
- **Licencia de esos datos:** [Creative Commons Attribution 4.0 (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
- **Vigencia del feed de origen:** 2024-09-08 a 2025-07-15. Está caducado.
- **Cambios:** se extrajeron paradas, coordenadas, líneas, orden y minutos entre paradas consecutivas; se restituyeron tildes que el CSV omitía; no se incluyen frecuencias ni el horario de servicio. Los minutos entre paradas solo se usan para estimar, de forma aproximada y marcada, un tranvía que el panel no anuncia. No son un horario.

La atribución también viaja dentro de `src/metrotenerife/data/catalog.json`.

## Licencia del código

El código de este repositorio se distribuye bajo la licencia MIT (archivo [LICENSE](LICENSE)), copyright 2026 Yann Favier (Yannedugo). Esa licencia cubre el código. No cubre los datos de terceros, las marcas ni el feed en vivo.

## Retirada

Si Metropolitano de Tenerife, S.A., el Cabildo Insular de Tenerife o quien resulte titular pide que se retire o se adapte este proyecto, se atenderá la solicitud. El contacto es el [issue tracker del repositorio](https://github.com/Yannedugo/metrotenerife-mcp/issues).
