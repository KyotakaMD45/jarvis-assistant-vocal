"""Regex fragments shared by command files (folded text: lowercase, no accents).

They include the variants the offline speech model really produces, e.g. "mets" is often
heard as "mais", "monte" as "montre", "fais" as "fait"/"c'est".
"""

OPEN = r"(?:ouvre|ouvrez|ouvrir|pauvre|lance|lancez|lancer|demarre|demarrez|demarrer|execute|affiche)"
CLOSE = r"(?:ferme|fermez|fermer|quitte|quittez|quitter)"
PUT = r"(?:mets|met|mais|mettre|metz|regle|reglez|regler|regles)"
PLAY = r"(?:joue|jouez|jouer|mets|met|mais|ecoute|ecouter|passe moi|passe-moi)"
UP = r"(?:monte|montre|montez|monter|augmente|augmentez|augmenter|hausse|remonte)"
DOWN = r"(?:baisse|baissez|baisser|diminue|diminuez|diminuer|reduis|reduisez|descends)"
DO = r"(?:fais|fait|faites|c'est|prends|prend|prenez)"
ART = r"(?:(?:les|le|la|une|un|des|du|de la|mon|ma|mes)\s+|l'\s*)?"
COMPUTER = r"(?:l'ordinateur|l'ordi|le pc|mon pc|mon ordinateur|l ordinateur|windows|la machine)"
