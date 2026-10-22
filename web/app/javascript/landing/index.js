import { Application } from "@hotwired/stimulus"
import EffectController from "landing/effect_controller"
import CommandsController from "landing/commands_controller"
import NavController from "landing/nav_controller"
import TourController from "landing/tour_controller"

const application = Application.start()
application.register("effect", EffectController)
application.register("commands", CommandsController)
application.register("nav", NavController)
application.register("tour", TourController)
