
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.widget import Widget
from kivy.uix.button import Button
from kivy.uix.behaviors import FocusBehavior
from kivy.properties import (ObjectProperty, NumericProperty,
                             OptionProperty, BooleanProperty)
from kivy.animation import Animation
from kivy import platform

from kivy.clock import Clock

from kivy.lib import osc

if platform != 'android':
    import subprocess
import sys

from os.path import realpath, join, dirname


class OutputLabel(Label):
    stream = OptionProperty('stdout', options=['stdout', 'stderr'])


class InputLabel(Label):
    index = NumericProperty(0)
    root = ObjectProperty()

    blue_shift = NumericProperty(0.)

    blue_anim = Animation(blue_shift=0., t='out_expo',
                          duration=0.5)

    def flash(self):
        self.blue_shift = 1.
        self.blue_anim.start(self)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super(InputLabel, self).on_touch_down(touch)

        self.flash()
        self.root.insert_previous_code(self.index)
        return True


class NonDefocusingButton(Button):
    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            FocusBehavior.ignored_touch.append(touch)
        return super(NonDefocusingButton, self).on_touch_down(touch)


class InterpreterScreen(Screen):
    pass


if platform == 'android':
    from kivy.uix.textinput import TextInput as InputWidget
else:
    from kivy.uix.textinput import TextInput as InputWidget
class InterpreterInput(InputWidget):
    root = ObjectProperty()

    def __init__(self, *args, **kwargs):
        super(InterpreterInput, self).__init__(*args, **kwargs)
        if platform != 'android':
            from pygments.lexers import PythonLexer
            self.lexer = PythonLexer()

    def insert_text(self, text, from_undo=False):
        super(InterpreterInput, self).insert_text(text, from_undo=from_undo)
        try:
            if (text == '\n' and
                self.text.split('\n')[-2][-1].strip()[-1] == ':'):
                previous_line = self.text.split('\n')[-2]
                num_spaces = len(previous_line) - len(previous_line.lstrip())
                for i in range(num_spaces + 4):
                    self.insert_text(' ')
            elif text == '\n':
                previous_line = self.text.split('\n')[-2]
                num_spaces = len(previous_line) - len(previous_line.lstrip())
                for i in range(num_spaces):
                    self.insert_text(' ')
        except IndexError:
            pass

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        if keycode[1] == 'enter' and 'shift' in modifiers:
            self.root.interpret_line_from_code_input()
            return
        super(InterpreterInput, self).keyboard_on_key_down(
            window, keycode, text, modifiers)

    def on_disabled(self, instance, value):
        if not value:
            self.focus = True


class InterpreterGui(BoxLayout):
    output_window = ObjectProperty()
    code_input = ObjectProperty()
    scrollview = ObjectProperty()

    input_fail_alpha = NumericProperty(0.)

    lock_input = BooleanProperty(False)

    def __init__(self, *args, **kwargs):
        super(InterpreterGui, self).__init__(*args, **kwargs)
        self.animation = Animation(input_fail_alpha=0., t='out_expo',
                                   duration=0.5)

        self.interpreter = InterpreterWrapper(self)

    def interpret_line_from_code_input(self):
        text = self.code_input.text
        if text == '':
            self.flash_input_fail()
            return
        self.code_input.text = ''
        self.interpret_line(text)
        self.code_input.focus = True

    def flash_input_fail(self):
        self.animation.stop(self)
        self.input_fail_alpha = 1.
        self.animation.start(self)

    def interpret_line(self, text):
        index = self.interpreter.interpret_line(text)
        self.add_input_label(text, index)

    def add_input_label(self, text, index):
        l = InputLabel(text=text, index=index, root=self)
        self.output_window.add_widget(l)
        self.scrollview.scroll_to(l)

    def add_output_label(self, text, stream='stdout'):
        l = OutputLabel(text=text, stream=stream)
        self.output_window.add_widget(l)
        self.scrollview.scroll_to(l)

    def add_break(self):
        b = BreakMarker()
        self.output_window.add_widget(b)
        self.scrollview.scroll_to(b)

    def insert_previous_code(self, index, clear=False):
        if clear:
            self.code_input.text = ''
        code = self.interpreter.inputs[index]
        if self.code_input.text == '':
            self.code_input.text = code
        else:
            self.code_input.text += '\n' + code


class BreakMarker(Widget):
    pass


class InterpreterWrapper(object):

    def __init__(self, gui):
        self.gui = gui

        self.start_interpreter()

        self.input_index = 0  # The current input number
        self.inputs = {}  # All the inputs so far

        self.interpreter_port = 3000
        self.receive_port = 3001

        self.init_osc()

    def start_interpreter(self):
        interpreter_script_path = join(dirname(realpath(__file__)),
                                       'interpreter_subprocess',
                                       'interpreter.py')

        if platform == 'android':
            from jnius import autoclass
            service = autoclass('net.inclem.pyde.ServiceInterpreter')
            mActivity = autoclass('org.kivy.android.PythonActivity').mActivity
            argument = ''
            service.start(mActivity, argument)
        else:
            # This may not actually work everywhere, but let's assume it does
            python_name = 'python{}'.format(sys.version_info.major)
            subprocess.Popen([python_name, '{}'.format(interpreter_script_path)])

    def init_osc(self):
        from kivy.lib import osc
        osc.init()
        self.oscid = osc.listen(ipAddr='127.0.0.1', port=self.receive_port)

        osc.bind(self.oscid, self.receive_osc_message, b'/stdout')
        osc.bind(self.oscid, self.receive_osc_message, b'/stderr')
        osc.bind(self.oscid, self.receive_osc_message, b'/interpreter')

    def begin_osc_listen(self):
        Clock.schedule_interval(self.read_osc_queue, 0.1)

    def end_osc_listen(self):
        Clock.unschedule(self.read_osc_queue)

    def read_osc_queue(self, *args):
        osc.readQueue(self.oscid)

    def receive_osc_message(self, message, *args):
        print('received message', message, args)
        address = message[0]
        body = [s.decode('utf-8') for s in message[2:]]

        if address == b'/interpreter':
            if body[0] == 'completed_exec':
                self.gui.add_break()
                self.gui.lock_input = False
                self.end_osc_listen()

        elif address == b'/stdout':
            self.gui.add_output_label(body[0], 'stdout')

        elif address == b'/stderr':
            self.gui.add_output_label(body[0], 'stderr')

    def interpret_line(self, text):
        self.send_osc_message(text.encode('utf-8'))
        self.gui.lock_input = True
        input_index = self.input_index
        self.inputs[input_index] = text
        self.input_index += 1
        self.begin_osc_listen()
        return input_index

    def send_osc_message(self, message):
        osc.sendMsg(b'/interpret', [message], port=self.interpreter_port,
                    typehint='b')
        print('sent', message)