// Format data copied from goat-odds.html and edison-odds.html. Keep the two in step when you retune a card.
// Card data: [type, set chance, tags]. Types: M monster, Sn normal spell, Sq quick-play, Sc continuous/equip/field, T trap.
// Tags: atk stops attacks, sum answers summons, rem S/T removal, mrem monster removal, neg negation, chaos Chaos monster, hatk hand trap vs attacks, draw advantage.
window.FORMATS = {};
FORMATS.goat = {
  title:"Goat",
  fmt:{
  sampleName:"Goat Control",
  handTag:"chaos", handTile:"Hand holds BLS or Chaos Sorcerer",
  example:{play:"Pot of Greed", draws:2, banish:null, reveal:"Mystical Space Typhoon"}
},
  db:{
  "Black Luster Soldier - Envoy of the Beginning":["M",0,["chaos","mrem"]],
  "Chaos Sorcerer":["M",0,["chaos","mrem"]],
  "Breaker the Magical Warrior":["M",0.15,["rem"]],
  "Tribe-Infecting Virus":["M",0.3,["mrem"]],
  "Jinzo":["M",0.05,[]],
  "Sinister Serpent":["M",0.4,[]],
  "Sangan":["M",0.9,[]],
  "Magician of Faith":["M",1,[]],
  "Tsukuyomi":["M",0.15,[]],
  "Airknight Parshath":["M",0.05,[]],
  "Morphing Jar":["M",1,[]],
  "D.D. Warrior Lady":["M",0.5,["mrem"]],
  "Exiled Force":["M",0.3,["mrem"]],
  "Spirit Reaper":["M",0.6,[]],
  "Kycoo the Ghost Destroyer":["M",0.3,[]],
  "Night Assailant":["M",1,["mrem"]],
  "Abyss Soldier":["M",0.2,["mrem"]],
  "Mystic Swordsman LV2":["M",0.4,[]],
  "Asura Priest":["M",0,[]],
  "Don Zaloog":["M",0.1,[]],
  "Dekoichi the Battlechanted Locomotive":["M",0.9,["draw"]],
  "Shining Angel":["M",0.6,[]],
  "Mystic Tomato":["M",0.5,[]],
  "Thestalos the Firestorm Monarch":["M",0.1,[]],
  "Zaborg the Thunder Monarch":["M",0.1,["mrem"]],
  "Gravekeeper's Spy":["M",1,[]],
  "Penguin Soldier":["M",1,["mrem"]],
  "Old Vindictive Magician":["M",1,["mrem"]],
  "Nimble Momonga":["M",0.7,[]],
  "Apprentice Magician":["M",1,[]],
  "Twin-Headed Behemoth":["M",0.3,[]],
  "Marauding Captain":["M",0.1,[]],
  "Pot of Greed":["Sn",0.05,["draw"]],
  "Graceful Charity":["Sn",0.05,["draw"]],
  "Heavy Storm":["Sn",0.05,["rem"]],
  "Mystical Space Typhoon":["Sq",0.5,["rem"]],
  "Snatch Steal":["Sc",0.05,["mrem"]],
  "Delinquent Duo":["Sn",0.05,[]],
  "Premature Burial":["Sc",0.1,[]],
  "Nobleman of Crossout":["Sn",0.05,["mrem"]],
  "Book of Moon":["Sq",0.7,["atk","sum"]],
  "Scapegoat":["Sq",0.95,["atk"]],
  "Metamorphosis":["Sq",0.3,[]],
  "Smashing Ground":["Sn",0.05,["mrem"]],
  "Swords of Revealing Light":["Sn",0.1,[]],
  "Enemy Controller":["Sq",0.6,["atk","mrem"]],
  "Confiscation":["Sn",0.05,[]],
  "Upstart Goblin":["Sn",0.05,["draw"]],
  "Reinforcement of the Army":["Sn",0.05,[]],
  "Painful Choice":["Sn",0.05,[]],
  "Card Destruction":["Sn",0.05,[]],
  "Creature Swap":["Sn",0.05,[]],
  "Lightning Vortex":["Sn",0.05,["mrem"]],
  "Fissure":["Sn",0.05,["mrem"]],
  "Tribute to the Doomed":["Sn",0.05,["mrem"]],
  "Mirage of Nightmare":["Sc",0.2,["draw"]],
  "Shrink":["Sq",0.6,["atk"]],
  "Rush Recklessly":["Sq",0.5,["atk"]],
  "Messenger of Peace":["Sc",0.2,[]],
  "Sakuretsu Armor":["T",1,["atk"]],
  "Mirror Force":["T",1,["atk"]],
  "Torrential Tribute":["T",1,["sum"]],
  "Bottomless Trap Hole":["T",1,["sum"]],
  "Trap Hole":["T",1,["sum"]],
  "Ring of Destruction":["T",1,["atk","sum","mrem"]],
  "Call of the Haunted":["T",1,[]],
  "Solemn Judgment":["T",1,["sum","neg"]],
  "Magic Cylinder":["T",1,["atk"]],
  "Waboku":["T",1,["atk"]],
  "Negate Attack":["T",1,["atk"]],
  "Dust Tornado":["T",1,["rem"]],
  "Magic Jammer":["T",1,["neg"]],
  "Seven Tools of the Bandit":["T",1,["neg"]],
  "Spell Shield Type-8":["T",1,["neg"]],
  "Royal Decree":["T",1,[]],
  "Return from the Different Dimension":["T",1,[]],
  "Ceasefire":["T",1,[]],
  "Reckless Greed":["T",1,["draw"]],
  "Threatening Roar":["T",1,["atk"]],
  "Draining Shield":["T",1,["atk"]],
  "Compulsory Evacuation Device":["T",1,["atk","sum","mrem"]],
  "Raigeki Break":["T",1,["atk","mrem"]],
  "Phoenix Wing Wind Blast":["T",1,["atk","mrem"]],
  "Ojama Trio":["T",1,[]]
},
  alias:{bls:"Black Luster Soldier - Envoy of the Beginning",envoy:"Black Luster Soldier - Envoy of the Beginning",cs:"Chaos Sorcerer",sorc:"Chaos Sorcerer",tiv:"Tribe-Infecting Virus",mof:"Magician of Faith",tsuku:"Tsukuyomi",airknight:"Airknight Parshath",jar:"Morphing Jar",ddwl:"D.D. Warrior Lady",pog:"Pot of Greed",gc:"Graceful Charity",charity:"Graceful Charity",hs:"Heavy Storm",mst:"Mystical Space Typhoon",ss:"Snatch Steal",duo:"Delinquent Duo",preme:"Premature Burial",pb:"Premature Burial",noble:"Nobleman of Crossout",bom:"Book of Moon",goat:"Scapegoat",goats:"Scapegoat",meta:"Metamorphosis",ec:"Enemy Controller",sak:"Sakuretsu Armor",saku:"Sakuretsu Armor",mf:"Mirror Force",tt:"Torrential Tribute",torrential:"Torrential Tribute",bth:"Bottomless Trap Hole",rod:"Ring of Destruction",ring:"Ring of Destruction",coth:"Call of the Haunted",solemn:"Solemn Judgment",swords:"Swords of Revealing Light",sorl:"Swords of Revealing Light",reaper:"Spirit Reaper",serpent:"Sinister Serpent",breaker:"Breaker the Magical Warrior",ter:"Thousand-Eyes Restrict"},
  sample:`# Goat Control, sample list. Edit it to match your opponent.
1 Black Luster Soldier - Envoy of the Beginning
1 Chaos Sorcerer
1 Breaker the Magical Warrior
1 Tribe-Infecting Virus
1 Jinzo
1 Sinister Serpent
1 Sangan
1 Magician of Faith
2 Tsukuyomi
2 Airknight Parshath
1 Morphing Jar
1 D.D. Warrior Lady
1 Spirit Reaper
1 Kycoo the Ghost Destroyer
1 Pot of Greed
1 Graceful Charity
1 Heavy Storm
1 Mystical Space Typhoon
1 Snatch Steal
1 Delinquent Duo
1 Premature Burial
1 Nobleman of Crossout
3 Book of Moon
2 Scapegoat
2 Metamorphosis
1 Smashing Ground
1 Enemy Controller
2 Sakuretsu Armor
1 Mirror Force
1 Torrential Tribute
1 Call of the Haunted
1 Ring of Destruction
1 Solemn Judgment

Extra Deck
1 Thousand-Eyes Restrict`
};
FORMATS.edison = {
  title:"Edison",
  fmt:{
  sampleName:"Blackwing",
  handTag:"hatk", handTile:"Hand holds Gorz, Tragoedia or Battle Fader",
  example:{play:"Allure of Darkness", draws:2, banish:"Blackwing - Kalut the Moon Shadow", reveal:"Mystical Space Typhoon"}
},
  db:{
  "Blackwing - Kalut the Moon Shadow":["M",0.05,[]],
  "Blackwing - Bora the Spear":["M",0.05,[]],
  "Blackwing - Gale the Whirlwind":["M",0.05,["mrem"]],
  "Blackwing - Shura the Blue Flame":["M",0.1,[]],
  "Blackwing - Sirocco the Dawn":["M",0,[]],
  "Blackwing - Blizzard the Far North":["M",0.05,[]],
  "Blackwing - Elphin the Raven":["M",0.05,[]],
  "Blackwing - Vayu the Emblem of Honor":["M",0.05,[]],
  "Gorz the Emissary of Darkness":["M",0,["hatk"]],
  "Tragoedia":["M",0,["hatk"]],
  "Battle Fader":["M",0,["hatk"]],
  "Swift Scarecrow":["M",0,["hatk"]],
  "Honest":["M",0.05,["hatk"]],
  "Kuriboh":["M",0,["hatk"]],
  "Caius the Shadow Monarch":["M",0.05,["mrem"]],
  "Raiza the Storm Monarch":["M",0.05,["mrem"]],
  "Zaborg the Thunder Monarch":["M",0.05,["mrem"]],
  "Card Trooper":["M",0.05,[]],
  "Snipe Hunter":["M",0.05,["mrem"]],
  "Cyber Dragon":["M",0,[]],
  "Dark Armed Dragon":["M",0,["mrem"]],
  "Dark Grepher":["M",0.05,[]],
  "Armageddon Knight":["M",0.3,[]],
  "Necro Gardna":["M",0.3,[]],
  "Plaguespreader Zombie":["M",0.2,[]],
  "Zombie Master":["M",0.2,[]],
  "Goblin Zombie":["M",0.4,[]],
  "Mezuki":["M",0.3,[]],
  "Il Blud":["M",0,[]],
  "Lonefire Blossom":["M",0.2,[]],
  "Glow-Up Bulb":["M",0.1,[]],
  "Spore":["M",0.1,[]],
  "Dandylion":["M",0.3,[]],
  "Quickdraw Synchron":["M",0,[]],
  "Debris Dragon":["M",0.05,[]],
  "Junk Synchron":["M",0.05,[]],
  "Ryko, Lightsworn Hunter":["M",1,["mrem"]],
  "Lumina, Lightsworn Summoner":["M",0.05,[]],
  "Jain, Lightsworn Paladin":["M",0.05,[]],
  "Garoth, Lightsworn Warrior":["M",0.05,[]],
  "Ehren, Lightsworn Monk":["M",0.6,["mrem"]],
  "Lyla, Lightsworn Sorceress":["M",0.2,["rem"]],
  "Celestia, Lightsworn Angel":["M",0,["mrem"]],
  "Judgment Dragon":["M",0,["mrem"]],
  "Wulf, Lightsworn Beast":["M",0,[]],
  "Treeborn Frog":["M",0.05,[]],
  "Sangan":["M",0.9,[]],
  "Marshmallon":["M",0.9,[]],
  "Spirit Reaper":["M",0.6,[]],
  "Mystic Tomato":["M",0.4,[]],
  "Magician of Faith":["M",1,[]],
  "D.D. Warrior Lady":["M",0.5,["mrem"]],
  "Breaker the Magical Warrior":["M",0.15,["rem"]],
  "Exiled Force":["M",0.3,["mrem"]],
  "Pot of Avarice":["Sn",0.05,["draw"]],
  "Allure of Darkness":["Sn",0.05,["draw"]],
  "Solar Recharge":["Sn",0.05,["draw"]],
  "Trade-In":["Sn",0.05,["draw"]],
  "Monster Reborn":["Sn",0.05,[]],
  "Heavy Storm":["Sn",0.05,["rem"]],
  "Giant Trunade":["Sn",0.05,["rem"]],
  "Mystical Space Typhoon":["Sq",0.5,["rem"]],
  "Brain Control":["Sn",0.05,["mrem"]],
  "Mind Control":["Sn",0.05,["mrem"]],
  "Book of Moon":["Sq",0.7,["atk","sum"]],
  "Smashing Ground":["Sn",0.05,["mrem"]],
  "Dark Hole":["Sn",0.05,["mrem"]],
  "Lightning Vortex":["Sn",0.05,["mrem"]],
  "Fissure":["Sn",0.05,["mrem"]],
  "Gold Sarcophagus":["Sn",0.05,[]],
  "Black Whirlwind":["Sc",0.15,[]],
  "Charge of the Light Brigade":["Sn",0.05,[]],
  "Foolish Burial":["Sn",0.05,[]],
  "One for One":["Sn",0.05,[]],
  "Reinforcement of the Army":["Sn",0.05,[]],
  "Burial from a Different Dimension":["Sq",0.3,[]],
  "Book of Life":["Sq",0.4,[]],
  "Limiter Removal":["Sq",0.5,[]],
  "Shrink":["Sq",0.6,["atk"]],
  "Enemy Controller":["Sq",0.6,["atk","mrem"]],
  "Scapegoat":["Sq",0.95,["atk"]],
  "Premature Burial":["Sc",0.1,[]],
  "Zombie World":["Sc",0.05,[]],
  "Swords of Revealing Light":["Sn",0.1,[]],
  "Card Destruction":["Sn",0.05,[]],
  "Mirror Force":["T",1,["atk"]],
  "Torrential Tribute":["T",1,["sum"]],
  "Bottomless Trap Hole":["T",1,["sum"]],
  "Trap Hole":["T",1,["sum"]],
  "Dimensional Prison":["T",1,["atk"]],
  "Solemn Judgment":["T",1,["sum","neg"]],
  "Solemn Warning":["T",1,["sum","neg"]],
  "Icarus Attack":["T",1,["atk","sum","mrem","rem"]],
  "Call of the Haunted":["T",1,[]],
  "Trap Dustshoot":["T",1,[]],
  "Mind Crush":["T",1,[]],
  "Royal Oppression":["T",1,["sum"]],
  "Royal Decree":["T",1,[]],
  "Magic Cylinder":["T",1,["atk"]],
  "Sakuretsu Armor":["T",1,["atk"]],
  "Compulsory Evacuation Device":["T",1,["atk","sum","mrem"]],
  "Threatening Roar":["T",1,["atk"]],
  "Waboku":["T",1,["atk"]],
  "Negate Attack":["T",1,["atk"]],
  "Scrap-Iron Scarecrow":["T",1,["atk"]],
  "Gravity Bind":["T",1,[]],
  "Starlight Road":["T",1,["neg"]],
  "Dust Tornado":["T",1,["rem"]],
  "Magic Jammer":["T",1,["neg"]],
  "Seven Tools of the Bandit":["T",1,["neg"]],
  "Dark Bribe":["T",1,["neg"]],
  "Divine Wrath":["T",1,["neg"]],
  "Trap Stun":["T",1,["neg"]],
  "Raigeki Break":["T",1,["atk","mrem"]],
  "Phoenix Wing Wind Blast":["T",1,["atk","mrem"]],
  "Return from the Different Dimension":["T",1,[]],
  "Ceasefire":["T",1,[]],
  "Skill Drain":["T",1,[]]
},
  alias:{kalut:"Blackwing - Kalut the Moon Shadow",bora:"Blackwing - Bora the Spear",gale:"Blackwing - Gale the Whirlwind",shura:"Blackwing - Shura the Blue Flame",sirocco:"Blackwing - Sirocco the Dawn",blizzard:"Blackwing - Blizzard the Far North",gorz:"Gorz the Emissary of Darkness",trag:"Tragoedia",fader:"Battle Fader",scarecrow:"Swift Scarecrow",caius:"Caius the Shadow Monarch",raiza:"Raiza the Storm Monarch",zaborg:"Zaborg the Thunder Monarch",trooper:"Card Trooper",cd:"Cyber Dragon",dad:"Dark Armed Dragon",ryko:"Ryko, Lightsworn Hunter",jd:"Judgment Dragon",poa:"Pot of Avarice",allure:"Allure of Darkness",reborn:"Monster Reborn",mr:"Monster Reborn",hs:"Heavy Storm",trunade:"Giant Trunade",mst:"Mystical Space Typhoon",bc:"Brain Control",bom:"Book of Moon",smash:"Smashing Ground",goldsarc:"Gold Sarcophagus",whirlwind:"Black Whirlwind",charge:"Charge of the Light Brigade",colb:"Charge of the Light Brigade",mf:"Mirror Force",tt:"Torrential Tribute",bth:"Bottomless Trap Hole",prison:"Dimensional Prison",dprison:"Dimensional Prison",judgment:"Solemn Judgment",warning:"Solemn Warning",icarus:"Icarus Attack",coth:"Call of the Haunted",dustshoot:"Trap Dustshoot",ced:"Compulsory Evacuation Device",goat:"Scapegoat"},
  sample:`# Blackwing, sample list. Edit it to match your opponent.
3 Blackwing - Kalut the Moon Shadow
3 Blackwing - Bora the Spear
2 Blackwing - Gale the Whirlwind
2 Blackwing - Shura the Blue Flame
1 Blackwing - Sirocco the Dawn
1 Blackwing - Blizzard the Far North
1 Gorz the Emissary of Darkness
1 Caius the Shadow Monarch
1 Battle Fader
1 Black Whirlwind
1 Monster Reborn
1 Heavy Storm
2 Mystical Space Typhoon
1 Brain Control
1 Pot of Avarice
1 Smashing Ground
2 Book of Moon
1 Allure of Darkness
1 Gold Sarcophagus
3 Icarus Attack
1 Mirror Force
1 Torrential Tribute
3 Bottomless Trap Hole
2 Dimensional Prison
1 Solemn Judgment
1 Solemn Warning
1 Call of the Haunted

Extra Deck
1 Stardust Dragon
1 Black-Winged Dragon`
};

// Archetype sketches used when no decklist is pasted. They were written from memory as rough starting points;
// the guess shifts toward whatever the opponent actually shows, and toward decks seen in your past duels.
FORMATS.goat.archetypes = [
  {name:"Goat Control", list:FORMATS.goat.sample},
  {name:"Chaos Warrior", list:`1 Black Luster Soldier - Envoy of the Beginning
1 Chaos Sorcerer
2 D.D. Warrior Lady
1 Exiled Force
1 Mystic Swordsman LV2
1 Blade Knight
1 Breaker the Magical Warrior
1 Tribe-Infecting Virus
1 Jinzo
1 Sinister Serpent
1 Sangan
1 Magician of Faith
1 Don Zaloog
1 Spirit Reaper
1 Asura Priest
1 Freed the Matchless General
1 Pot of Greed
1 Graceful Charity
1 Heavy Storm
1 Mystical Space Typhoon
1 Snatch Steal
1 Delinquent Duo
1 Premature Burial
1 Nobleman of Crossout
2 Reinforcement of the Army
2 Book of Moon
1 Smashing Ground
1 Enemy Controller
1 Scapegoat
2 Sakuretsu Armor
1 Mirror Force
1 Torrential Tribute
1 Ring of Destruction
1 Call of the Haunted
1 Solemn Judgment
1 Bottomless Trap Hole`},
  {name:"Flip Control", list:`1 Black Luster Soldier - Envoy of the Beginning
1 Chaos Sorcerer
1 Magician of Faith
2 Old Vindictive Magician
2 Night Assailant
1 Penguin Soldier
1 Morphing Jar
1 Sangan
1 Sinister Serpent
2 Tsukuyomi
1 Breaker the Magical Warrior
1 Tribe-Infecting Virus
1 Spirit Reaper
1 Apprentice Magician
1 Pot of Greed
1 Graceful Charity
1 Heavy Storm
1 Mystical Space Typhoon
1 Snatch Steal
1 Delinquent Duo
1 Premature Burial
1 Nobleman of Crossout
2 Book of Moon
1 Scapegoat
1 Swords of Revealing Light
1 Book of Taiyou
1 Smashing Ground
2 Sakuretsu Armor
1 Mirror Force
1 Torrential Tribute
1 Ring of Destruction
1 Call of the Haunted
1 Solemn Judgment
1 Magic Cylinder
1 Dust Tornado`},
  {name:"Monarch", list:`2 Zaborg the Thunder Monarch
1 Thestalos the Firestorm Monarch
2 Mobius the Frost Monarch
1 Black Luster Soldier - Envoy of the Beginning
1 Chaos Sorcerer
1 Breaker the Magical Warrior
1 Tribe-Infecting Virus
1 Sangan
1 Magician of Faith
1 Sinister Serpent
1 Spirit Reaper
1 D.D. Warrior Lady
1 Morphing Jar
1 Tsukuyomi
1 Mystic Tomato
1 Pot of Greed
1 Graceful Charity
1 Heavy Storm
1 Mystical Space Typhoon
1 Snatch Steal
1 Delinquent Duo
1 Premature Burial
1 Nobleman of Crossout
2 Book of Moon
2 Scapegoat
1 Enemy Controller
1 Soul Exchange
2 Sakuretsu Armor
1 Mirror Force
1 Torrential Tribute
1 Ring of Destruction
1 Call of the Haunted
1 Solemn Judgment
1 Royal Decree
1 Dust Tornado`},
];
FORMATS.edison.archetypes = [
  {name:"Blackwing", list:FORMATS.edison.sample},
  {name:"Lightsworn", list:`3 Ryko, Lightsworn Hunter
2 Lumina, Lightsworn Summoner
2 Lyla, Lightsworn Sorceress
1 Garoth, Lightsworn Warrior
1 Ehren, Lightsworn Monk
1 Jain, Lightsworn Paladin
2 Wulf, Lightsworn Beast
1 Celestia, Lightsworn Angel
2 Judgment Dragon
1 Necro Gardna
1 Gorz the Emissary of Darkness
1 Honest
2 Charge of the Light Brigade
2 Solar Recharge
1 Monster Reborn
1 Heavy Storm
2 Mystical Space Typhoon
1 Brain Control
1 Book of Moon
1 Gold Sarcophagus
1 Mirror Force
1 Torrential Tribute
1 Solemn Judgment
1 Solemn Warning
2 Bottomless Trap Hole
2 Dimensional Prison
1 Trap Dustshoot
1 Call of the Haunted
1 Mind Crush`},
  {name:"Zombie", list:`3 Goblin Zombie
2 Zombie Master
2 Mezuki
1 Plaguespreader Zombie
1 Il Blud
2 Card Trooper
1 Gorz the Emissary of Darkness
1 Armageddon Knight
1 Tragoedia
1 Battle Fader
1 Book of Life
1 Foolish Burial
1 Monster Reborn
1 Heavy Storm
2 Mystical Space Typhoon
1 Brain Control
1 Book of Moon
1 Gold Sarcophagus
1 Pot of Avarice
1 Burial from a Different Dimension
1 One for One
1 Smashing Ground
1 Giant Trunade
1 Mirror Force
1 Torrential Tribute
1 Solemn Judgment
1 Solemn Warning
2 Bottomless Trap Hole
2 Dimensional Prison
1 Call of the Haunted
1 Trap Dustshoot
1 Mind Crush`},
  {name:"Quickdraw Plant", list:`3 Quickdraw Synchron
3 Lonefire Blossom
1 Spore
1 Glow-Up Bulb
1 Dandylion
2 Debris Dragon
1 Plaguespreader Zombie
2 Card Trooper
1 Gorz the Emissary of Darkness
1 Tragoedia
1 Armageddon Knight
1 Sangan
1 One for One
1 Foolish Burial
1 Monster Reborn
1 Heavy Storm
2 Mystical Space Typhoon
1 Brain Control
1 Book of Moon
1 Pot of Avarice
1 Gold Sarcophagus
1 Burial from a Different Dimension
1 Dark Hole
1 Mirror Force
1 Torrential Tribute
1 Solemn Judgment
1 Solemn Warning
2 Bottomless Trap Hole
1 Dimensional Prison
1 Trap Dustshoot
1 Mind Crush
1 Call of the Haunted`},
  {name:"Frog Monarch", list:`1 Treeborn Frog
2 Swap Frog
2 Ronintoadin
1 Dupe Frog
3 Caius the Shadow Monarch
2 Raiza the Storm Monarch
1 Zaborg the Thunder Monarch
1 Gorz the Emissary of Darkness
1 Battle Fader
1 Cyber Dragon
1 Sangan
2 Enemy Controller
1 Brain Control
2 Soul Exchange
1 Foolish Burial
1 Monster Reborn
1 Heavy Storm
2 Mystical Space Typhoon
1 Book of Moon
1 Giant Trunade
1 Pot of Avarice
1 Gold Sarcophagus
1 Mirror Force
1 Torrential Tribute
1 Solemn Judgment
1 Solemn Warning
2 Bottomless Trap Hole
2 Dimensional Prison
1 Trap Dustshoot
1 Mind Crush`},
  {name:"Gladiator Beasts", list:`2 Gladiator Beast Laquari
3 Gladiator Beast Bestiari
2 Gladiator Beast Darius
1 Gladiator Beast Equeste
1 Gladiator Beast Murmillo
2 Test Tiger
1 Gladiator Beast Hoplomus
1 Gorz the Emissary of Darkness
1 Gladiator Proving Ground
1 Reinforcement of the Army
1 Monster Reborn
1 Heavy Storm
2 Mystical Space Typhoon
1 Brain Control
1 Book of Moon
1 Gold Sarcophagus
2 Enemy Controller
1 Smashing Ground
1 Giant Trunade
1 Swords of Revealing Light
3 Gladiator Beast War Chariot
1 Solemn Judgment
1 Solemn Warning
1 Torrential Tribute
1 Mirror Force
2 Bottomless Trap Hole
2 Dimensional Prison
1 Trap Dustshoot
1 Mind Crush`},
];
