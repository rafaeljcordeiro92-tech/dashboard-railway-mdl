ARQUIVOS PARA O RAILWAY

1) Use estes arquivos no deploy:
- dashboard_railway_main_headless.py
- dashboard_sales_worker_headless.py
- railway_scheduler.py
- Procfile
- railway.json
- requirements.txt

2) No railway_scheduler.py, se quiser, troque os nomes dos scripts para:
- dashboard_sales_worker_headless.py
- dashboard_railway_main_headless.py

3) Variáveis recomendadas:
- APP_TZ=America/Sao_Paulo
- RUN_ON_RAILWAY=1

4) Observação:
Esses arquivos já foram ajustados para rodar Chrome em modo headless no Railway.
Se o Railway ainda acusar falta de navegador/driver nos logs, aí a próxima etapa será ajustar o ambiente de build do container.
