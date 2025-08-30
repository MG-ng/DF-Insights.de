from abc import ABC, abstractmethod


# Define an abstract base class (interface)
class Animal(ABC):

    @abstractmethod
    def eat(self):
        pass

    @abstractmethod
    def travel(self):
        pass

# Implement the abstract base class in a subclass
class Dog(Animal):

    def eat(self):
        print("Dog eats food.")

    def travel(self):
        print("Dog travels by walking.")

# Implement the abstract base class in a subclass
class Horse(Animal):

    def eat(self):
        print("Horse eats food.")

    def travel(self):
        print("Horse travels by walking.")

# Example usage
my_dog = Dog()
my_dog.eat()
my_dog.travel()
