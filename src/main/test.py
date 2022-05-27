import re

line = '<http://dbpedia.org/resource/Water_softening> <http://dbpedia.org/ontology/abstract> ' \
       '"L\'adoucissement de l\'eau est un procédé de traitement initialement destiné à réduire la dureté de l\'eau (due à la présence de sels de métaux alcalino-terreux : ' \
       'carbonates, sulfates et chlorures de calcium et de magnésium). Cette opération entre parfois dans le cadre de l\'épuration physico-chimique de l\'eau où elle peut' \
       ' accompagner d’autres modalités de traitement de l\'eau (filtration, désinfection, dénitrification, élimination des pesticides) en vue de sa distribution comme ' \
       'eau potable ou pour des usages techniques nécessitant une eau déminéralisée. D\'autres techniques d\'adoucissement existent actuellement sur le marché,' \
       ' comme par exemple les adoucisseurs avec injection de CO2 permettant de maintenir le carbonate de calcium en solution sous forme de bicarbonate de calcium et' \
       ' d\'empêcher ainsi sa précipitation. L\'eau ainsi traitée est sous-saturée vis-à-vis de CaCO3 (indice de saturation < 0) et donc agressive, permettant même la' \
       ' dissolution de dépôts de calcaire existants. Des appareils adoucisseurs \"magnétiques\" et des adoucisseurs émettant des \"fréquences micro-ondes\" sont disponibles' \
       ' dans le commerce depuis longtemps mais leur efficacité n\'est pas démontrée. Le principe de fonctionnement physico-chimique de ces appareils n\'est pas compris et' \
       ' ils sont sujets à controverses. L\'adoucissement supposé obtenu par ces appareils ne repose pas sur une diminution du titre hydrotimétrique (TH) lui-même mais' \
       ' permettrait de lutter contre ses désagréments."@fr .'

def split_and_keep(seperator, s, maxsplit=0):
    return re.split(';_', re.sub(seperator, lambda match: ';_' + match.group() , s),maxsplit=maxsplit)

cols = split_and_keep(r' (".*"|<http)',line.strip(),maxsplit=2)
print(cols[2])
cols = [col.strip() for col in cols]
cols2 = split_and_keep(r'@[a-z]{2} \.|@[a-z]{2} ;',cols[2])
cols[2] = cols2[0]
if len(cols2) > 1:
  cols3 = re.split(r'@[a-z]{2} ',cols2[1])
  cols.append(cols3[1])

