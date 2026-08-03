from digital_bast.web.app import create_app
from digital_bast.web.production import production_dependencies

app = create_app(production_dependencies())
