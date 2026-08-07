from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from settings.config import settings
from database.tables import table_class

#Database setup
# SQLite по умолчанию запрещает использовать соединение из другого потока,
# а FastAPI выполняет синхронные зависимости в пуле потоков — на websocket
# сессия создаётся в одном потоке, а закрывается в другом.
sqlite_args = (
    {"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite") else {}
)
engine = create_engine(settings.DATABASE_URL, connect_args=sqlite_args)

session_local = sessionmaker(autocommit=False, bind=engine)

#Create tables
def create_tables():
    table_class.metadata.create_all(bind=engine)

#Dependency in database
def get_db():
    db = session_local()      #open new session
    try:
        yield db            #session to endpoint
    finally:
        db.close()          #close session
