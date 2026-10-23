"""Investigador: navegación online acotada para completar lo que un agente no sabe.

  safe_fetch  lector web seguro: solo GET de texto, sin direcciones locales
              ni privadas (ni tras redirecciones), con límites de tamaño
  search      buscadores: SearXNG local (seguro) y DuckDuckGo (más libre)
  researcher  el subproceso: una pregunta, presupuesto fijo, profundidad 1,
              caché y registro; devuelve extractos con su fuente (datos)
"""
