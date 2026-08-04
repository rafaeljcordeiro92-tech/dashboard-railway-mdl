AJUSTE RAILWAY - CHROME/SELENIUM

Use estes arquivos no lugar dos anteriores:
- dashboard_railway_main_headless_v2.py
- dashboard_sales_worker_headless_v2.py
- railway_scheduler_headless.py
- Procfile  -> conteúdo: web: python railway_scheduler_headless.py
- nixpacks.toml
- requirements.txt

O que mudou:
1) Instalamos chromium + chromedriver via nixpacks.toml
2) Os scripts v2 tentam usar explicitamente:
   - GOOGLE_CHROME_BIN / CHROME_BIN
   - CHROMEDRIVER / CHROMEDRIVER_PATH
3) Voltamos a usar o scheduler headless padrão

No Railway:
- mantenha APP_TZ=America/Sao_Paulo
- mantenha RUN_ON_RAILWAY=1
- pode remover FORCE_RUN_SALES_ON_BOOT e FORCE_RUN_COBRANCA_ON_BOOT depois do teste
- para um teste imediato, pode manter as 2 em 1 só temporariamente

Próximo passo:
1) substituir os arquivos antigos pelos v2
2) adicionar nixpacks.toml
3) ajustar Procfile para railway_scheduler_headless.py
4) git add . / commit / push
5) redeploy
