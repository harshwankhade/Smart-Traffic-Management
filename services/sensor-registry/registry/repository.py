from .models import IntersectionRow, SensorRow


def get_intersection(session, identifier):
    return session.get(IntersectionRow, identifier)


def get_sensor(session, identifier):
    return session.get(SensorRow, identifier)


def create(session, model, fields):
    row = model(**fields)
    session.add(row)
    session.commit()
    return row


def update(session, row, fields):
    for key, value in fields.items():
        setattr(row, key, value)
    session.commit()
    return row
