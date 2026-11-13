# Agregar una inmobiliaria

1. **Registrar** desde el dashboard (pestaña Fuentes) o `POST /sources` con `base_url`, `region` y, si se
   conoce, la URL del listado de terrenos en `start_urls`.
2. **Revisar la inspección**: `GET /jobs/{id}` muestra el perfil (`rendering`, `pagination`, `listing_patterns`,
   `detail_strategy`, `confidence`), notas y fichas de muestra. Confianza < 0.5 → revisar a mano.
3. **Crawlear**: `POST /sources/{id}/crawl`. En el dashboard revisar `% con precio`, `% con superficie` y errores.

## Si el genérico no alcanza

En orden de preferencia (no escribir un scraper salvo que haga falta):

- **Override de perfil** (`POST /sources/{id}/profile`): fija `listing_patterns`, `pagination`, `rendering`.
  Nunca es pisado por inspecciones automáticas.
- **Selectores manuales** (`PATCH /sources/{id}` con `manual_overrides.selectors`):

  ```json
  {"manual_overrides": {"selectors": {"title": "h1.titulo", "price": ".precio", "area": ".sup-total",
                                      "description": "#descripcion", "location": ".zona", "photos": ".galeria img"}}}
  ```

- **Adaptador de sitio**: subclase de `adapters.base.SiteAdapter` decorada con `@register`, con `domains`.

## Sitios con JavaScript

Si la inspección marca `rendering: javascript`, habilitar `ENABLE_PLAYWRIGHT=true` y reconstruir la imagen con
`--build-arg WITH_PLAYWRIGHT=1`.
