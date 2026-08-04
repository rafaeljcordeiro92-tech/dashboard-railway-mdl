AJUSTE ONLINE 100% - RAILWAY COM DOCKER + XVFB

Arquivos criados:
- dashboard_railway_main_xvfb.py
- dashboard_sales_worker_xvfb.py
- Dockerfile
- entrypoint.sh

IDEIA:
Em vez de insistir no Chrome headless puro, vamos rodar o Chromium em um display virtual (Xvfb).
Isso costuma resolver crashes do renderer/DevTools em containers Linux.

COMO USAR:
1) Substitua:
   - dashboard_railway_main_headless.py  pelo conteúdo de dashboard_railway_main_xvfb.py
   - dashboard_sales_worker_headless.py pelo conteúdo de dashboard_sales_worker_xvfb.py

2) Mantenha o scheduler:
   - railway_scheduler_headless.py

3) Procfile:
   - você pode até remover o Procfile quando usar Dockerfile
   - se quiser manter, deixe: web: python railway_scheduler_headless.py
   - com Dockerfile, o Railway normalmente obedecerá o CMD do Dockerfile

4) Adicione ao projeto:
   - Dockerfile
   - entrypoint.sh

5) Faça git add / commit / push e redeploy.

OBS:
- Pode manter FORCE_RUN_SALES_ON_BOOT=1 e FORCE_RUN_COBRANCA_ON_BOOT=1 só para teste.
- Depois que funcionar, remova essas 2 variáveis.
