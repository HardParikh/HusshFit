from django.shortcuts import render,redirect
from django.http import JsonResponse
import openai
from django.contrib import auth
from django.contrib.auth.models import User
from .models import Chat
from django.utils import timezone
import os
import logging
import requests
import json
from typing import Optional
import functools
import inspect
import re

openai_api_key = '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'
openai.api_key = openai_api_key 
os.environ['OPENAI_API_KEY']=openai_api_key
nut_api_key = 'zUdlbhd2kgKgQoQ4iVnXiA==5WyhjdvgoJwFJUFa'
os.environ['NUT_API_KEY']=nut_api_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys_msg = """Our Assistant, known as HusshFit, is a cutting-edge software system powered by OpenAI's GPT-3.5 technology. Specifically tailored for health, fitness, and nutrition-related tasks, it excels at delivering valuable calculations related to health metrics, such as Basal Metabolic Rate (BMR) and Total Daily Energy Expenditure (TDEE), employing well-recognized equations like Harris-Benedict and Mifflin-St Jeor. Additionally, it can effortlessly retrieve nutritional information for various food items through an external API.

HusshFit boasts the ability to engage in meaningful conversations and furnish insightful responses pertaining to health and nutrition. Based on the input it receives, the assistant can swiftly compute and furnish crucial health metric values, empowering users to gain a deeper understanding of their energy expenditure and nutritional intake.

This dynamic assistant continually evolves and refines its capabilities to offer more precise and informative responses. Its functionalities include processing and comprehending substantial amounts of text, generating human-like responses, and providing in-depth explanations about intricate health metrics.

Whether you seek insights into your daily energy expenditure, require assistance in calculating your BMR, or wish to access nutritional data about your meals, HusshFit is at your service. The ultimate objective is to promote and facilitate a healthier lifestyle by enhancing the accessibility of nutritional and metabolic information.
"""

class Agent:
    def __init__(
        self,
        openai_api_key: str = openai.api_key,
        model_name: str = 'gpt-3.5-turbo-16k-0613',
        functions: Optional[list] = None
    ):
        openai.api_key = openai_api_key
        self.model_name = model_name
        self.functions = self._parse_functions(functions)
        self.func_mapping = self._create_func_mapping(functions)
        self.chat_history = [{'role': 'system', 'content': sys_msg}]

    def _parse_functions(self, functions: Optional[list]) -> Optional[list]:
        if functions is None:
            return None
        return [func_to_json(func) for func in functions]

    def _create_func_mapping(self, functions: Optional[list]) -> dict:
        if functions is None:
            return {}
        return {func.__name__: func for func in functions}

    def _create_chat_completion(
        self, messages: list, use_functions: bool=True
    ) -> openai.ChatCompletion:
        if use_functions and self.functions:
            res = openai.ChatCompletion.create(
                model=self.model_name,
                messages=messages,
                functions=self.functions
            )
        else:
            res = openai.ChatCompletion.create(
                model=self.model_name,
                messages=messages
            )
        return res

    def _generate_response(self) -> openai.ChatCompletion:
        while True:
            print('.', end='')
            res = self._create_chat_completion(
                self.chat_history + self.internal_thoughts
            )
            finish_reason = res.choices[0].finish_reason

            if finish_reason == 'stop' or len(self.internal_thoughts) > 3:
                final_thought = self._final_thought_answer()
                final_res = self._create_chat_completion(
                    self.chat_history + [final_thought],
                    use_functions=False
                )
                return final_res
            elif finish_reason == 'function_call':
                self._handle_function_call(res)
            else:
                raise ValueError(f"Unexpected finish reason: {finish_reason}")

    def _handle_function_call(self, res: openai.ChatCompletion):
        self.internal_thoughts.append(res.choices[0].message.to_dict())
        func_name = res.choices[0].message.function_call.name
        args_str = res.choices[0].message.function_call.arguments
        result = self._call_function(func_name, args_str)
        res_msg = {'role': 'assistant', 'content': (f"The answer is {result}.")}
        self.internal_thoughts.append(res_msg)

    def _call_function(self, func_name: str, args_str: str):
        args = json.loads(args_str)
        logger.info(f"Function name: {func_name}")
        logger.info(f"Args: {args}")
        func = self.func_mapping[func_name]
        logger.info(f"Function object: {func}")
        res = func(**args)
        return res

    def _final_thought_answer(self):
        thoughts = ("To answer the question I will use these step by step instructions."
                    "\n\n")
        for thought in self.internal_thoughts:
            if 'function_call' in thought.keys():
                thoughts += (f"I will use the {thought['function_call']['name']} "
                             "function to calculate the answer with arguments "
                             + thought['function_call']['arguments'] + ".\n\n")
            else:
                thoughts += thought["content"] + "\n\n"
        self.final_thought = {
            'role': 'assistant',
            'content': (f"{thoughts} Based on the above, I will now answer the "
                        "question, this message will only be seen by me so answer with "
                        "the assumption with that the user has not seen this message.")
        }
        return self.final_thought

    def ask(self, query: str) -> openai.ChatCompletion:
        self.internal_thoughts = []
        self.chat_history.append({'role': 'user', 'content': query})
        res = self._generate_response()
        self.chat_history.append(res.choices[0].message.to_dict())
        return res

class FitnessAgent:
    def __init__(self, openai_api_key: openai.api_key, nut_api_key: str):
        self.openai_api_key = openai_api_key
        self.nut_api_key = nut_api_key

        self.agent = Agent(
            openai_api_key=self.openai_api_key,
            functions=[self.get_nutritional_info, self.calculate_bmr, self.calculate_tdee, self.calculate_ibw, self.calculate_bmi, self.calculate_calories_to_lose_weight]
        )

    def get_nutritional_info(self, query: str) -> dict:
        """Fetch the nutritional information for a specific food item.

        :param query: The food item to get nutritional info for
        :return: The nutritional information of the food item
        """
        api_url = 'https://api.api-ninjas.com/v1/nutrition?query={}'.format(query)
        response = requests.get(api_url, timeout=100, headers={'X-Api-Key': self.nut_api_key})

        if response.status_code == requests.codes.ok:
            return response.json()  # Use json instead of text for a more structured data
        else:
            return {"Error": response.status_code, "Message": response.text}
        
    def calculate_bmi(self, weight: float, height: float) -> float:
        """Calculate the Body Mass Index (BMI) for a person.

        :param weight: The weight of the person in kg
        :param height: The height of the person in cm
        :return: The BMI of the person
        """
        height_meters = height / 100  # convert cm to meters
        bmi = weight / (height_meters ** 2)
        return round(bmi, 2)  # round to 2 decimal places for readability
    
    def calculate_calories_to_lose_weight(self, desired_weight_loss_kg: float) -> float:
        """Calculate the number of calories required to lose a certain amount of weight.

        :param desired_weight_loss_kg: The amount of weight the person wants to lose, in kilograms
        :return: The number of calories required to lose that amount of weight
        """
        calories_per_kg_fat = 7700  # Approximate number of calories in a kg of body fat
        return desired_weight_loss_kg * calories_per_kg_fat


    def calculate_bmr(self, weight: float, height: float, age: int, gender: str, equation: str = 'mifflin_st_jeor') -> float:
        """Calculate the Basal Metabolic Rate (BMR) for a person.

        :param weight: The weight of the person in kg.
        :param height: The height of the person in cm.
        :param age: The age of the person in years.
        :param gender: The gender of the person ('male' or 'female')
        :param equation: The equation to use for BMR calculation ('harris_benedict' or 'mifflin_st_jeor')
        :return: The BMR of the person
        """
        if equation.lower() == 'mifflin_st_jeor':
            if gender.lower() == 'male':
                return (10 * weight) + (6.25 * height) - (5 * age) + 5
            else:  # 'female'
                return (10 * weight) + (6.25 * height) - (5 * age) - 161
        else:  # 'harris_benedict'
            if gender.lower() == 'male':
                return 88.362 + (13.397 * weight) + (4.799 * height) - (5.677 * age)
            else:  # 'female'
                return 447.593 + (9.247 * weight) + (3.098 * height) - (4.330 * age)

    def calculate_tdee(self, bmr: float, activity_level: str) -> float:
        """Calculate the Total Daily Energy Expenditure (TDEE) for a person.

        :param bmr: The BMR of the person
        :param activity_level: The activity level of the person
        ('sedentary', 'lightly_active', 'moderately_active', 'very_active', 'super_active')
        :return: The TDEE of the person
        """
        activity_factors = {
            'sedentary': 1.2,
            'lightly_active': 1.375,
            'moderately_active': 1.55,
            'very_active': 1.725,
            'super_active': 1.9,
        }
        return bmr * activity_factors.get(activity_level, 1)

    def calculate_ibw(self, height: float, gender: str) -> float:
        """Calculate the Ideal Body Weight (IBW).

        :param height: The height of the person in inches
        :param gender: The gender of the person ("male" or "female")
        :return: The Ideal Body Weight in kg
        """
        if gender.lower() == 'male':
            if height <= 60:  # 5 feet = 60 inches
                return 50
            else:
                return 50 + 2.3 * (height - 60)
        elif gender.lower() == 'female':
            if height <= 60:
                return 45.5
            else:
                return 45.5 + 2.3 * (height - 60)
        else:
            raise ValueError("Invalid gender. Expected 'male' or 'female'.")

    def ask(self, question: str):
        response = self.agent.ask(question)
        return response

    def view_functions(self):
        return self.agent.functions

    def view_chat_history(self):
        return self.agent.chat_history
    
def type_mapping(dtype):
    if dtype == float:
        return "number"
    elif dtype == int:
        return "integer"
    elif dtype == str:
        return "string"
    else:
        return "string"


def extract_params(doc_str: str):
    params_str = [line for line in doc_str.split("\n") if line.strip()]
    params = {}
    for line in params_str:
        if line.strip().startswith(':param'):
            param_match = re.findall(r'(?<=:param )\w+', line)
            if param_match:
                param_name = param_match[0]
                desc_match = line.replace(f":param {param_name}:", "").strip()
                if desc_match:
                    params[param_name] = desc_match
    return params


def func_to_json(func):
    if isinstance(func, functools.partial) or isinstance(func, functools.partialmethod):
        fixed_args = func.keywords
        _func = func.func
        if isinstance(func, functools.partial) and (fixed_args is None or fixed_args == {}):
            fixed_args = dict(zip(func.func.__code__.co_varnames, func.args))
    else:
        fixed_args = {}
        _func = func
    func_name = _func.__name__
    argspec = inspect.getfullargspec(_func)
    func_doc = inspect.getdoc(_func)
    func_description = ''.join([line for line in func_doc.split("\n") if not line.strip().startswith(':')])
    param_details = extract_params(func_doc) if func_doc else {}
    params = {}
    for param_name in argspec.args:
        if param_name not in fixed_args.keys():
            params[param_name] = {
                "description": param_details.get(param_name) or "",
                "type": type_mapping(argspec.annotations.get(param_name, type(None)))
            }
    _required = [i for i in argspec.args if i not in fixed_args.keys()]
    if inspect.getfullargspec(_func).defaults:
        _required = [argspec.args[i] for i, a in enumerate(argspec.args) if
                     argspec.args[i] not in inspect.getfullargspec(_func).defaults and argspec.args[
                         i] not in fixed_args.keys()]
    return {
        "name": func_name,
        "description": func_description,
        "parameters": {
            "type": "object",
            "properties": params
        },
        "required": _required
    }



fitness_agent = FitnessAgent(openai_api_key, nut_api_key)

def ask_openai(message):
    res = fitness_agent.ask(message)
    chat_response = res['choices'][0]['message']['content']
    return chat_response

def chatbot(request):
    chats = Chat.objects.filter(user=request.user.id)


    if request.method == 'POST':
        message = request.POST.get('message')
        response = ask_openai(message)

        chat = Chat(user=request.user, message=message, response=response, created_at=timezone.now)
        chat.save()
        return JsonResponse({'message': message, 'response': response})
    return render(request, 'chatbot.html', {'chats': chats})


def login(request):
    if request.method=='POST':
        username = request.POST['username']
        password = request.POST['password']
        user = auth.authenticate(request, username=username, password=password)
        if user is not None:
            auth.login(request, user)
            return redirect('chatbot')
        else:
            error_message = 'Invalid username or password'
            return render(request, 'login.html', {'error_message': error_message})
    else:
        return render(request, 'login.html')

def register(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password1 = request.POST['password1']
        password2 = request.POST['password2']

        if password1==password2:
            try:
                user = User.objects.create_user(username, email, password1)
                user.save()
                auth.login(request, user)
                return redirect('chatbot')
            except:
                error_message = 'Error creating account'
            return render(request, 'register.html', {'error_message': error_message})
        else:
            error_message = "Password don't match" 
            return render(request, 'register.html', {'error_message': error_message})
    return render(request, 'register.html')

def logout(request):
    auth.logout(request)
    return redirect('/')
