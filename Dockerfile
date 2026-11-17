# Imagen de la Lambda del agente de onboarding (construida por `sam build`)
FROM public.ecr.aws/lambda/python:3.12

COPY requirements-lambda.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements-lambda.txt

COPY app/ ${LAMBDA_TASK_ROOT}/app/
COPY data/ ${LAMBDA_TASK_ROOT}/data/

CMD ["app.lambda_handler.handler"]
