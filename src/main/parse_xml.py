import re

class XMLParser:
	def __init__(self):
		self.line = None
		self.data = []

	def read_tag(self, line):
		match = re.search(r'<(\/?)([a-z]+).*>',line)

		if not match:
			return None, False

		ending = match.group(1) != ''
		tag = match.group(2)

		return tag, ending

	def read_one_line_tag_value(self, line):
		match = re.search(r'<[a-z]+>(.*)<\/[a-z]+>', line)

		if not match:
			return None

		value = match.group(1)

		return value

	def read_value_following_tag(self, line):
		match = re.search(r'<.*>(.*)', line)

		if not match:
			return None

		value = match.group(1)

		return value

	def read_record(self,file):
		header_first_line = file.readline()
		header_tag, ending = self.read_tag(header_first_line)


		title, text, start_text = None, None, False
		next_line = file.readline()
		next_tag, ending = self.read_tag(next_line)
		while header_tag != next_tag:
			# print(next_line)
			# print('NEXT TAG: ' + next_tag)

			try:
				if next_tag == 'title':
					title = self.read_one_line_tag_value(next_line)
					# print(title)

				if next_tag == 'text' and not ending:
					start_text = True
					text = self.read_text(next_line,file)

					self.data.append({'title': title.encode('utf-8'), 'text': text.encode('utf-8')})
					# print('----------------------')
					# print('TITLE: ' + title)
					# print('TEXT: ' + text)

					title, text = None, None

				next_line = file.readline()
				next_tag, ending =self.read_tag(next_line)
			except:
				pass

	def read_text(self, line, file):
		text = ''
		value = self.read_value_following_tag(line) 
		text += value if value else ''

		next_line = file.readline()
		next_tag, ending = self.read_tag(next_line)
		while True:
			# print(next_line)
			# print(next_tag)
			if next_tag == 'text' and ending:
				return text
			
			text += next_line if next_line else ''

			next_line = file.readline()
			next_tag, ending =self. read_tag(next_line)
