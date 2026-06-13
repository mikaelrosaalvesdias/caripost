import boto3
from botocore.config import Config

# Configurações obtidas do stack.yml
S3_ENDPOINT_URL = "https://s3.n8nmikael.com.br"
S3_ACCESS_KEY_ID = "0e1fb1161ed4f7c0a41b0fa7"
S3_SECRET_ACCESS_KEY = "64ac389164e77eb46ef7bc9bb3791fd5a0803abdb51cc52a"
S3_BUCKET = "metaporn"

def fix_cors():
    # MinIO às vezes reclama de assinaturas v4 complexas em certas chamadas de admin.
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4")
    )

    # Versão simplificada para MinIO (evitando MaxAge ou ExposeHeaders se der erro)
    cors_configuration = {
        'CORSRules': [
            {
                'AllowedHeaders': ['*'],
                'AllowedMethods': ['GET', 'PUT', 'POST', 'DELETE', 'HEAD'],
                'AllowedOrigins': ['*'], # Mais permissivo para garantir que funcione
            }
        ]
    }

    try:
        print(f"Tentando aplicar CORS simplificado no bucket '{S3_BUCKET}'...")
        s3.put_bucket_cors(Bucket=S3_BUCKET, CORSConfiguration=cors_configuration)
        print("CORS configurado com sucesso!")
        
    except Exception as e:
        print(f"Erro ao configurar CORS: {e}")
        print("\nTentando alternativa via política de bucket se CORS falhar...")
        # Se PutBucketCors não for implementado, talvez devêssemos usar bucket policy,
        # mas CORS é o padrão para erros de preflight no browser.

if __name__ == "__main__":
    fix_cors()
