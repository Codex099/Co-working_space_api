from fastapi import APIRouter
from fastapi.responses import JSONResponse
from services.user_service import (
    create_user,
    get_user_by_email_logic,
    login_user,
    signup_request,
    confirm_signup,
    get_user_by_id_logic,
    update_user_by_id
)
from schemas import (
    UserCreate,
    LoginRequest,
    SignupRequest,
    ConfirmSignupRequest,
    UpdateUserRequest,
)

router = APIRouter()

@router.post('/users')
async def create_user_route(data: UserCreate):
    resp, code = create_user(data.model_dump())
    return JSONResponse(content=resp, status_code=code)

@router.get('/users/email/{email}')
def get_user_by_email_route(email: str):
    resp, code = get_user_by_email_logic(email)
    return JSONResponse(content=resp, status_code=code)

@router.post('/login')
async def login_user_route(data: LoginRequest):
    resp, code = login_user(data.model_dump())
    return JSONResponse(content=resp, status_code=code)

@router.post('/sign-in-request')
async def sign_in_request_route(data: SignupRequest):
    resp, code = signup_request(data.model_dump())
    return JSONResponse(content=resp, status_code=code)

@router.post('/confirm-sign-in')
def confirm_sign_in_route(data: ConfirmSignupRequest):
    resp, status_code = confirm_signup(data.email, data.code)
    return JSONResponse(content=resp, status_code=status_code)

@router.get('/users/{user_id}')
def get_user_by_id_route(user_id: int):
    resp, code = get_user_by_id_logic(user_id)
    return JSONResponse(content=resp, status_code=code)

@router.put('/users/{user_id}')
def update_user_by_id_route(user_id: int, data: UpdateUserRequest):
    resp, code = update_user_by_id(user_id, data.model_dump(exclude_unset=True))
    return JSONResponse(content=resp, status_code=code)
